# --- app.py (完整替换版本) ---

import os
import requests
import json
import docker
from flask import Flask, render_template, jsonify, request
from urllib.parse import urlparse, urljoin
from dotenv import load_dotenv
from bs4 import BeautifulSoup, Tag
from werkzeug.utils import secure_filename

# --- 应用初始化和配置加载 ---
app = Flask(__name__)
load_dotenv()

BOOKMARKS_DIR = 'bookmarks_history'
if not os.path.exists(BOOKMARKS_DIR):
    os.makedirs(BOOKMARKS_DIR)

# API 配置
LUCKY_API_ENDPOINT = os.getenv('LUCKY_API_ENDPOINT')
LUCKY_API_TOKEN = os.getenv('LUCKY_API_TOKEN')
SUNPANEL_API_BASE = os.getenv('SUNPANEL_API_BASE')
SUNPANEL_API_TOKEN = os.getenv('SUNPANEL_API_TOKEN')


# 检查 Docker Socket 是否可用
def is_docker_socket_available():
    try:
        docker.from_env()
        return True
    except:
        return False


DOCKER_SOCKET_AVAILABLE = is_docker_socket_available()
LUCKY_CONFIG_AVAILABLE = bool(LUCKY_API_ENDPOINT and LUCKY_API_TOKEN)


# --- 辅助函数 ---
def get_host_ip_from_endpoints():
    endpoints_to_check = [
        os.getenv('LUCKY_API_ENDPOINT'),
        os.getenv('SUNPANEL_API_BASE')
    ]
    for url_string in endpoints_to_check:
        if not url_string: continue
        try:
            parsed_url = urlparse(url_string)
            if parsed_url.hostname:
                print(f"自动检测到宿主机 IP: {parsed_url.hostname}")
                return parsed_url.hostname
        except Exception:
            continue
    print("警告：未能自动检测到宿主机 IP。")
    return None


HOST_IP = get_host_ip_from_endpoints()


def get_lucky_proxies():
    # 如果 Lucky 配置不可用，直接返回空列表
    if not LUCKY_CONFIG_AVAILABLE:
        return [], None
    headers = {
        'openToken': LUCKY_API_TOKEN,
        'User-Agent': 'Sun-Panel-Icon-Adder/1.0'
    }
    try:
        api_url = f"{LUCKY_API_ENDPOINT.rstrip('/')}/api/webservice/rules"
        response = requests.get(api_url, headers=headers, timeout=10)
        response.raise_for_status()
        lucky_data = response.json()
        all_rules = []
        if isinstance(lucky_data.get('ruleList'), list):
            for rule_group in lucky_data['ruleList']:
                if isinstance(rule_group.get('ProxyList'), list):
                    all_rules.extend(rule_group['ProxyList'])
        if not all_rules: return [], "未找到任何'ProxyList'"
        simplified_proxies = []
        for rule in all_rules:
            if (rule.get('Domains') and rule.get('Locations')):
                lan_url = rule['Locations'][0]
                if not lan_url.startswith(('http://', 'https://')):
                    lan_url = f"http://{lan_url}"
                parsed_url = urlparse(lan_url)
                description_ip = parsed_url.netloc or parsed_url.path.split(
                    '/')[0]
                simplified_proxies.append({
                    'name':
                    rule.get('Remark') or rule['Domains'][0],
                    'domain':
                    rule['Domains'][0],
                    'external_url':
                    f"https://{rule['Domains'][0]}",
                    'internal_ip':
                    lan_url,
                    'description':
                    description_ip,
                    'status':
                    '运行中' if rule.get('Enable') else '已停止'
                })
        return simplified_proxies, None
    except requests.exceptions.RequestException as e:
        return [], f"连接 Lucky API 失败: {e}"
    except Exception as e:
        return [], f"处理 Lucky 数据时发生错误: {e}"


def get_docker_containers():
    # 如果 Docker Socket 不可用，直接返回空列表
    if not DOCKER_SOCKET_AVAILABLE:
        return [], None

    try:
        client = docker.from_env()
        all_docker_containers = client.containers.list(all=True)
        containers = []
        for container in all_docker_containers:
            internal_ip = ""
            if container.status == 'running' and container.ports:
                for _, host_bindings in container.ports.items():
                    if host_bindings:
                        ip = host_bindings[0].get('HostIp', 'localhost')
                        if ip == '0.0.0.0' and HOST_IP:
                            ip = HOST_IP
                        internal_ip = f"http://{ip}:{host_bindings[0]['HostPort']}"
                        break
            description_ip = ""
            if internal_ip:
                description_ip = urlparse(internal_ip).netloc
            containers.append({
                'name':
                container.name,
                'domain':
                container.name,
                'external_url':
                '',
                'internal_ip':
                internal_ip,
                'description':
                description_ip,
                'status':
                '运行中' if container.status == 'running' else '已停止',
                'source': ['Docker']
            })
        return containers, None
    except Exception as e:
        return [], f"获取 Docker 容器失败: {str(e)}"


def merge_sources(docker_containers, lucky_proxies):
    merged_items = {
        c['internal_ip']: c
        for c in docker_containers if c['internal_ip']
    }
    final_list = [c for c in docker_containers if not c['internal_ip']]
    for proxy in lucky_proxies:
        ip = proxy['internal_ip']
        if ip and ip in merged_items:
            existing_item = merged_items[ip]
            existing_item['name'] = proxy['name']
            existing_item['domain'] = proxy['domain']
            existing_item['external_url'] = proxy['external_url']
            if 'Lucky' not in existing_item['source']:
                existing_item['source'].append('Lucky')
        else:
            proxy['source'] = ['Lucky']
            final_list.append(proxy)
    final_list.extend(merged_items.values())
    final_list.sort(key=lambda item: item['name'].lower())
    return final_list


# --- 全新的、更可靠的书签解析逻辑 ---
def parse_bookmarks_html(file_path):
    """
    解析浏览器导出的 HTML 书签文件的新方法。
    该方法首先提取所有节点（文件夹和书签），然后通过栈来重建层级结构，
    能可靠地处理不规范的 <p> 标签。
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'lxml')

        # 找到所有 <dt> 标签，它们是构成书签结构的基本单元
        all_dts = soup.find_all('dt')
        if not all_dts:
            return [], "未在文件中找到有效的书签列表 (<DT> 标签)"

        nodes = []
        for dt in all_dts:
            link = dt.find('a', recursive=False)
            folder = dt.find('h3', recursive=False)

            if link:
                href = link.get('href')
                if href and href.startswith(('http://', 'https://')):
                    title = link.get_text(
                        strip=True) or urlparse(href).hostname or "无标题"
                    nodes.append({
                        'type': 'bookmark',
                        'name': title,
                        'domain': urlparse(href).hostname,
                        'external_url': href,
                        'internal_ip': '',
                        'description': href,
                        'status': 'Imported',
                        'source': ['Bookmark']
                    })
            elif folder:
                folder_name = folder.get_text(strip=True)
                # 使用一个特殊的 'level' 属性来标记文件夹的层级，便于后续处理
                # <H3> 标签的层级与它所在的 <DL> 标签的嵌套层级相关
                level = len(dt.find_parents('dl'))
                nodes.append({
                    'type': 'folder',
                    'title': folder_name,
                    'children': [],
                    'level': level
                })

        # 使用栈来重建树状结构
        if not nodes:
            return [], "解析后未发现任何有效的书签或文件夹"

        # 结果树
        result_tree = []
        # 辅助栈，用于追踪当前父文件夹路径
        parent_stack = []

        for node in nodes:
            if node['type'] == 'folder':
                node_level = node.pop('level')  # 取出并删除level
                # 如果当前文件夹的层级比栈顶文件夹深，则它是栈顶的子文件夹
                # 如果层级相同或更浅，则需要回退栈
                while parent_stack and parent_stack[-1]['level'] >= node_level:
                    parent_stack.pop()

                if not parent_stack:
                    # 如果栈为空，说明是顶层文件夹
                    result_tree.append(node)
                else:
                    # 否则，是栈顶文件夹的子文件夹
                    parent_stack[-1]['node']['children'].append(node)

                # 将当前文件夹压入栈中
                parent_stack.append({'level': node_level, 'node': node})

            elif node['type'] == 'bookmark':
                if not parent_stack:
                    # 如果没有父文件夹，则是顶层书签
                    result_tree.append(node)
                else:
                    # 否则，添加到当前父文件夹
                    parent_stack[-1]['node']['children'].append(node)

        return result_tree, None

    except Exception as e:
        return [], f"解析书签文件失败: {e}"


# --- Flask 路由 (保持不变) ---
@app.route('/')
def index():
    lucky_proxies, lucky_error = get_lucky_proxies()
    docker_containers, docker_error = get_docker_containers()
    all_items = merge_sources(docker_containers, lucky_proxies)
    error = None

    # 只有当存在实际错误时才显示错误信息
    if lucky_error and docker_error:
        error = f"Lucky 错误: {lucky_error} | Docker 错误: {docker_error}"
    elif lucky_error:
        error = lucky_error
    elif docker_error:
        error = docker_error
    elif not LUCKY_CONFIG_AVAILABLE and not DOCKER_SOCKET_AVAILABLE:
        error = "注意：Lucky 和 Docker 功能均已禁用（缺少配置或 Socket）"
    elif not LUCKY_CONFIG_AVAILABLE:
        error = "注意：Lucky 功能已禁用（缺少配置）"
    elif not DOCKER_SOCKET_AVAILABLE:
        error = "注意：Docker 功能已禁用（Socket 不可用）"

    return render_template('index.html', proxies=all_items, error=error)


@app.route('/api/get_icon_urls')
def get_icon_urls():
    url = request.args.get('url')
    if not url: return jsonify({'error': 'URL parameter is required'}), 400
    try:
        parsed_url = urlparse(url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        icon_urls = []
        html_icons = []

        common_locations = [
            '/favicon.ico', '/favicon.png', '/favicon.jpg', '/favicon.svg',
            '/apple-touch-icon.png'
        ]
        for location in common_locations:
            icon_url = urljoin(base_url, location)
            try:
                if requests.head(icon_url, timeout=2,
                                 allow_redirects=True).status_code == 200:
                    icon_urls.append({
                        'url': icon_url,
                        'type': 'common_location',
                        'name': location.split('/')[-1]
                    })
            except requests.RequestException:
                continue

        try:
            response = requests.get(url,
                                    timeout=5,
                                    headers={'User-Agent': 'Mozilla/5.0'})
            if response.status_code == 200:
                import re
                content = response.text
                patterns = [
                    r'<link[^>]*rel=["\'](?:icon|shortcut icon|apple-touch-icon)["\'][^>]*href=["\']([^"\']+)["\']',
                    r'<meta[^>]*name=["\']msapplication-TileImage["\'][^>]*content=["\']([^"\']+)["\']'
                ]
                for pattern in patterns:
                    for match in re.finditer(pattern, content, re.IGNORECASE):
                        icon_path = match.group(1)
                        html_icons.append({
                            'url':
                            urljoin(base_url, icon_path),
                            'type':
                            'html_link',
                            'name':
                            f'HTML: {icon_path.split("/")[-1]}'
                        })
        except requests.RequestException:
            pass

        seen_urls = set()
        all_icons = []
        for icon in icon_urls + html_icons:
            if icon['url'] not in seen_urls:
                seen_urls.add(icon['url'])
                all_icons.append(icon)

        all_icons.sort(
            key=lambda x: (x['type'] != 'common_location', x['url']))
        return jsonify({'iconUrls': all_icons})
    except Exception as e:
        return jsonify({'error': f'获取图标链接失败: {str(e)}'}), 500


@app.route('/api/sunpanel/groups')
def sunpanel_get_groups():
    if not (SUNPANEL_API_BASE and SUNPANEL_API_TOKEN):
        return jsonify({'error': 'SunPanel API 未在环境变量中配置'}), 500
    try:
        url = f"{SUNPANEL_API_BASE}/itemGroup/getList"
        headers = {
            'token': SUNPANEL_API_TOKEN,
            'Content-Type': 'application/json'
        }
        response = requests.post(url, headers=headers, json={}, timeout=10)
        response.raise_for_status()
        if not response.text:
            return jsonify({'error': 'SunPanel API 返回了空响应'}), 500
        data = response.json()
        if data.get('code') != 0:
            return jsonify({'error': data.get('msg',
                                              '从 SunPanel 获取分组失败')}), 400
        return jsonify(data.get('data', {}).get('list', []))
    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'连接 SunPanel API 失败: {e}'}), 500
    except json.JSONDecodeError:
        return jsonify(
            {'error': 'SunPanel API 返回了非JSON格式的响应，请检查API端点或SunPanel状态'}), 500
    except Exception as e:
        return jsonify({'error': f'处理分组数据时发生错误: {e}'}), 500


@app.route('/api/sunpanel/item/create', methods=['POST'])
def sunpanel_create_item():
    try:
        data = request.get_json()
        if not data: return jsonify({'error': 'No data provided'}), 400
        sunpanel_url = f"{SUNPANEL_API_BASE}/item/create"
        headers = {
            'Content-Type': 'application/json',
            'token': SUNPANEL_API_TOKEN
        }
        response = requests.post(sunpanel_url,
                                 json=data,
                                 headers=headers,
                                 timeout=30)
        response.raise_for_status()
        sunpanel_response = response.json()
        if isinstance(sunpanel_response, dict):
            code = sunpanel_response.get('code', 0)
            if code != 0:
                error_map = {1100: '令牌过期', 1000: '参数格式错误', 1202: '唯一名称已存在'}
                return jsonify({
                    'error':
                    error_map.get(code, sunpanel_response.get('msg', '未知错误')),
                    'code':
                    code
                }), 400
        return jsonify(sunpanel_response), response.status_code
    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'请求 SunPanel API 失败: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'服务器内部错误: {str(e)}'}), 500


@app.route('/api/bookmarks/upload', methods=['POST'])
def upload_bookmark():
    if 'bookmarkFile' not in request.files:
        return jsonify({'error': '没有找到文件'}), 400
    file = request.files['bookmarkFile']
    if file.filename == '': return jsonify({'error': '没有选择文件'}), 400
    if file and file.filename.endswith('.html'):
        filename = secure_filename(file.filename)
        filepath = os.path.join(BOOKMARKS_DIR, filename)
        file.save(filepath)
        bookmarks, error = parse_bookmarks_html(filepath)
        if error: return jsonify({'error': error}), 500
        return jsonify(bookmarks)
    return jsonify({'error': '无效的文件格式, 请上传 .html 文件'}), 400


@app.route('/api/bookmarks/history')
def get_bookmark_history():
    try:
        files = [f for f in os.listdir(BOOKMARKS_DIR) if f.endswith('.html')]
        return jsonify(
            sorted(
                files,
                key=lambda f: os.path.getmtime(os.path.join(BOOKMARKS_DIR, f)),
                reverse=True))
    except Exception as e:
        return jsonify({'error': f"读取历史记录失败: {e}"}), 500


@app.route('/api/bookmarks/load/<filename>')
def load_bookmark_file(filename):
    s_filename = secure_filename(filename)
    filepath = os.path.join(BOOKMARKS_DIR, s_filename)
    if not os.path.exists(filepath): return jsonify({'error': '文件未找到'}), 404
    bookmarks, error = parse_bookmarks_html(filepath)
    if error: return jsonify({'error': error}), 500
    return jsonify(bookmarks)


# --- 主程序入口 ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3003, debug=False)
