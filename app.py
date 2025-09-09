import os
import requests
import json
import docker  # 导入官方 Docker SDK
from flask import Flask, render_template, jsonify, request
from urllib.parse import urlparse, urljoin
from dotenv import load_dotenv

# --- 应用初始化和配置加载 ---
app = Flask(__name__)
load_dotenv()  # 加载 .env 文件中的环境变量

# API 配置
LUCKY_API_ENDPOINT = os.getenv('LUCKY_API_ENDPOINT')
LUCKY_API_TOKEN = os.getenv('LUCKY_API_TOKEN')
SUNPANEL_API_BASE = os.getenv('SUNPANEL_API_BASE')
SUNPANEL_API_TOKEN = os.getenv('SUNPANEL_API_TOKEN')


# --- 自动检测宿主机 IP ---
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


# --- 数据获取函数 (保持不变) ---
def get_lucky_proxies():
    if not (LUCKY_API_ENDPOINT and LUCKY_API_TOKEN):
        return [], "Lucky API 端点或 Token 未配置"
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


# --- 核心合并逻辑 (保持不变) ---
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
            existing_item['source'].append('Lucky')
        else:
            proxy['source'] = ['Lucky']
            final_list.append(proxy)

    final_list.extend(merged_items.values())
    final_list.sort(key=lambda item: item['name'].lower())
    return final_list


# --- Flask 路由和视图 ---
@app.route('/')
def index():
    lucky_proxies, lucky_error = get_lucky_proxies()
    docker_containers, docker_error = get_docker_containers()
    all_items = merge_sources(docker_containers, lucky_proxies)
    error = lucky_error or docker_error
    return render_template('index.html', proxies=all_items, error=error)


@app.route('/api/proxies')
def api_proxies():
    lucky_proxies, lucky_error = get_lucky_proxies()
    docker_containers, docker_error = get_docker_containers()
    all_items = merge_sources(docker_containers, lucky_proxies)
    if lucky_error and docker_error:
        return jsonify(
            {'error': f"Lucky: {lucky_error}, Docker: {docker_error}"}), 500
    elif lucky_error:
        return jsonify({'error': lucky_error}), 500
    elif docker_error:
        return jsonify({'error': docker_error}), 500
    return jsonify(all_items)


@app.route('/api/get_icon_urls')
def get_icon_urls():
    url = request.args.get('url')
    if not url: return jsonify({'error': 'URL parameter is required'}), 400
    try:
        parsed_url = urlparse(url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        icon_urls, html_icons = [], []
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
                    r'<link[^>]*rel=["\'](?:icon|shortcut icon)["\'][^>]*href=["\']([^"\']+)["\']',
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
        seen_urls, all_icons = set(), []
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
    """代理 SunPanel 获取分组列表的 API 请求"""
    if not (SUNPANEL_API_BASE and SUNPANEL_API_TOKEN):
        return jsonify({'error': 'SunPanel API 未在环境变量中配置'}), 500

    try:
        url = f"{SUNPANEL_API_BASE}/itemGroup/getList"
        headers = {
            'token': SUNPANEL_API_TOKEN,
            'Content-Type': 'application/json'
        }
        # **核心修改**: 将 GET 请求改为 POST 请求，并发送一个空的json体
        response = requests.post(url, headers=headers, json={}, timeout=10)
        response.raise_for_status()

        # 增加对空响应的判断
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


# --- 主程序入口 ---
if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=3003, debug=True, use_reloader=False)
    finally:
        pass
