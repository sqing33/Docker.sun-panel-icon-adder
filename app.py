import os
import requests
import json
import tempfile
import shutil
import subprocess
from flask import Flask, render_template, jsonify, request, send_file
from urllib.parse import urlparse, urljoin
from dotenv import load_dotenv

app = Flask(__name__)
load_dotenv()  # 加载 .env 文件

# Lucky API 配置
LUCKY_API_ENDPOINT = os.getenv('LUCKY_API_ENDPOINT')
LUCKY_API_TOKEN = os.getenv('LUCKY_API_TOKEN')

# SunPanel API 配置
SUNPANEL_API_BASE = os.getenv('SUNPANEL_API_BASE')
SUNPANEL_API_TOKEN = os.getenv('SUNPANEL_API_TOKEN')


def get_lucky_proxies():
    """获取 Lucky 反向代理规则列表"""
    if not (LUCKY_API_ENDPOINT and LUCKY_API_TOKEN):
        return [], "Lucky API 端点或Token未在环境变量中配置"

    headers = {
        'openToken': LUCKY_API_TOKEN,
        'User-Agent': 'Lucky-Proxy-Table/1.0'
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

        if not all_rules:
            return [], "在Lucky API的响应中未能找到任何'ProxyList'"

        simplified_proxies = []
        for rule in all_rules:
            if (rule.get('Domains') and isinstance(rule.get('Domains'), list)
                    and rule['Domains'] and rule.get('Locations')
                    and isinstance(rule.get('Locations'), list)
                    and rule['Locations']):

                domain = rule['Domains'][0]
                name = rule.get('Remark') or domain
                full_url = f"https://{domain}"
                lan_url = rule['Locations'][0]

                # 解析内网地址（保留端口号）
                parsed_url = urlparse(lan_url)
                if parsed_url.hostname and parsed_url.port:
                    lan_host = f"{parsed_url.hostname}:{parsed_url.port}"
                elif parsed_url.hostname:
                    lan_host = parsed_url.hostname
                else:
                    lan_host = lan_url

                # 提取纯IP:port用于描述
                description_ip = lan_host
                if '://' in description_ip:
                    # 移除http://或https://前缀
                    description_ip = description_ip.split('://')[1]
                if '/' in description_ip:
                    # 移除路径部分
                    description_ip = description_ip.split('/')[0]

                simplified_proxies.append({
                    'name':
                    name,
                    'domain':
                    domain,
                    'external_url':
                    full_url,
                    'internal_ip':
                    lan_host,
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


@app.route('/')
def index():
    # 获取Lucky代理和Docker容器，合并列表
    lucky_proxies, lucky_error = get_lucky_proxies()
    docker_containers, docker_error = get_docker_containers()
    
    # 合并列表并去重（基于域名/名称）
    all_items = []
    seen_names = set()
    
    # 先添加Lucky代理
    for proxy in lucky_proxies:
        if proxy['domain'] not in seen_names:
            seen_names.add(proxy['domain'])
            all_items.append(proxy)
    
    # 再添加Docker容器（不去重已存在的Lucky项目）
    for container in docker_containers:
        if container['domain'] not in seen_names:
            seen_names.add(container['domain'])
            all_items.append(container)
    
    # 如果有错误，只显示第一个错误
    error = lucky_error or docker_error
    
    return render_template('index.html', proxies=all_items, error=error)


@app.route('/api/proxies')
def api_proxies():
    # 获取Lucky代理和Docker容器，合并列表
    lucky_proxies, lucky_error = get_lucky_proxies()
    docker_containers, docker_error = get_docker_containers()
    
    # 合并列表并去重（基于域名/名称）
    all_items = []
    seen_names = set()
    
    # 先添加Lucky代理
    for proxy in lucky_proxies:
        if proxy['domain'] not in seen_names:
            seen_names.add(proxy['domain'])
            all_items.append(proxy)
    
    # 再添加Docker容器（不去重已存在的Lucky项目）
    for container in docker_containers:
        if container['domain'] not in seen_names:
            seen_names.add(container['domain'])
            all_items.append(container)
    
    if lucky_error and docker_error:
        return jsonify({'error': f"Lucky: {lucky_error}, Docker: {docker_error}"}), 500
    elif lucky_error:
        return jsonify({'error': lucky_error}), 500
    elif docker_error:
        return jsonify({'error': docker_error}), 500
        
    return jsonify(all_items)


@app.route('/api/get_icon_urls')
def get_icon_urls():
    """获取网站的所有可能图标地址"""
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'URL parameter is required'}), 400

    try:
        parsed_url = urlparse(url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"

        icon_urls = []

        # 常见的favicon位置
        common_locations = [
            '/favicon.ico', '/favicon.png', '/favicon.jpg', '/favicon.jpeg',
            '/favicon.svg', '/apple-touch-icon.png',
            '/apple-touch-icon-precomposed.png',
            '/apple-touch-icon-120x120.png', '/apple-touch-icon-180x180.png'
        ]

        # 检查常见位置的图标
        for location in common_locations:
            icon_url = urljoin(base_url, location)
            try:
                response = requests.head(icon_url,
                                         timeout=3,
                                         allow_redirects=True)
                if response.status_code == 200:
                    icon_urls.append({
                        'url': icon_url,
                        'type': 'common_location',
                        'name': location.split('/')[-1]
                    })
            except:
                continue

        # 从HTML中查找图标链接
        html_icons = []
        try:
            response = requests.get(url,
                                    timeout=10,
                                    headers={'User-Agent': 'Mozilla/5.0'})
            if response.status_code == 200:
                content = response.text

                # 查找所有icon相关的link标签
                import re
                icon_patterns = [
                    r'<link[^>]*rel=["\'](?:icon|shortcut icon)["\'][^>]*href=["\']([^"\']+)["\']',
                    r'<link[^>]*href=["\']([^"\']+)["\'][^>]*rel=["\'](?:icon|shortcut icon)["\']',
                    r'<meta[^>]*name=["\']msapplication-TileImage["\'][^>]*content=["\']([^"\']+)["\']'
                ]

                for pattern in icon_patterns:
                    matches = re.finditer(pattern, content, re.IGNORECASE)
                    for match in matches:
                        icon_path = match.group(1)
                        icon_url = urljoin(base_url, icon_path)
                        html_icons.append({
                            'url':
                            icon_url,
                            'type':
                            'html_link',
                            'name':
                            f'HTML: {icon_path.split("/")[-1]}'
                        })
        except:
            pass

        # 去重并合并结果
        seen_urls = set()
        all_icons = []

        for icon in icon_urls + html_icons:
            if icon['url'] not in seen_urls:
                seen_urls.add(icon['url'])
                all_icons.append(icon)

        # 按类型排序：common_location优先
        all_icons.sort(
            key=lambda x: (x['type'] != 'common_location', x['url']))

        return jsonify({'iconUrls': all_icons})

    except Exception as e:
        return jsonify({'error': f'Failed to get icon URLs: {str(e)}'}), 500


def get_docker_containers():
    """获取 Docker 容器列表"""
    try:
        # 使用Docker API通过Unix socket获取容器信息
        import socket
        import json
        
        # 创建Unix socket连接
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect('/var/run/docker.sock')
        
        # 发送HTTP请求到Docker API
        request = "GET /containers/json HTTP/1.1\r\nHost: localhost\r\n\r\n"
        sock.send(request.encode())
        
        # 读取响应
        response = b''
        while True:
            data = sock.recv(4096)
            if not data:
                break
            response += data
        
        sock.close()
        
        # 解析HTTP响应
        headers, body = response.split(b'\r\n\r\n', 1)
        containers_data = json.loads(body.decode())
        
        containers = []
        for container in containers_data:
            name = container['Names'][0].lstrip('/')
            image = container['Image']
            
            # 解析端口信息
            internal_ip = ""
            ports_info = container.get('Ports', [])
            if ports_info:
                # 获取第一个公开的端口
                for port_info in ports_info:
                    if port_info.get('PublicPort'):
                        ip = port_info.get('IP', 'localhost')
                        if ip == '0.0.0.0':
                            ip = 'localhost'
                        internal_ip = f"{ip}:{port_info['PublicPort']}"
                        break
            
            containers.append({
                'name': name,
                'domain': name,
                'external_url': '',  # 外部地址留空
                'internal_ip': internal_ip,
                'description': f"{image} ({internal_ip if internal_ip else '无端口暴露'})",
                'status': '运行中',
                'source': 'docker'  # 标记来源为Docker
            })
        
        return containers, None
        
    except Exception as e:
        return [], f"获取Docker容器失败: {str(e)}"



@app.route('/api/sunpanel/item/create', methods=['POST'])
def sunpanel_create_item():
    """代理 SunPanel 创建项目的 API 请求，解决 CORS 问题"""
    try:
        # 从请求中获取数据
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400


        # 转发请求到 SunPanel API
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

        # 处理SunPanel特定的错误码
        if isinstance(sunpanel_response, dict):
            code = sunpanel_response.get('code', 0)
            if code != 0:  # 非0表示有错误
                error_map = {
                    1100: '令牌过期',
                    1000: '参数格式错误',
                    1001: '参数格式错误',
                    1202: '唯一名称已存在',
                    1203: '无记录'
                }
                error_msg = sunpanel_response.get('msg', '未知错误')
                return jsonify({
                    'error': error_map.get(code, error_msg),
                    'code': code,
                    'details': error_msg
                }), 400

        return jsonify(sunpanel_response), response.status_code

    except requests.exceptions.RequestException as e:
        return jsonify({'error':
                        f'SunPanel API request failed: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500
    finally:
        pass


if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=3003, debug=True)
    finally:
        pass
