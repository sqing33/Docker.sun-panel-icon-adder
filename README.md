# Sun-Panel 图标添加工具

一个用于将 Docker 容器和 Lucky 代理服务导入到 Sun-Panel 的工具，同时支持从浏览器书签文件导入网站链接。

## 功能特性

- **服务集成**: 自动获取 Docker 容器和 Lucky 代理服务信息
- **书签导入**: 支持导入浏览器导出的 HTML 书签文件
- **图标获取**: 自动检测并获取网站图标
- **Sun-Panel 集成**: 直接将服务或书签添加到 Sun-Panel
- **文件夹分类**: 支持书签文件夹结构的识别和分类显示
- **历史记录**: 保留导入的书签文件历史记录

## 项目地址

- **Github**：https://github.com/sqing33/Docker.sun-panel-icon-adder
- **DockerHub**：https://hub.docker.com/r/sqing33/sun-panel-icon-adder

## 项目结构

```
.
├── app.py              # 主应用程序文件
├── Dockerfile          # Docker 构建文件
├── docker-compose.yml  # Docker Compose 配置文件
├── requirements.txt    # Python 依赖文件
├── .env                # 环境变量配置文件
├── templates/
│   └── index.html      # 前端界面文件
├── static/
│   └── favicon.ico     # 网站图标
└── bookmarks_history/  # 书签文件存储目录
```

## Docker Compose 配置

```yaml
services:
  sun-panel-icon-adder:
    image: ghcr.io/sqing33/sun-panel-icon-adder
    container_name: sun-panel-icon-adder
    restart: always
    ports:
      - "3003:3003"
    environment:
      - SUNPANEL_API_BASE=http://192.168.1.100:3002/openapi/v1
      - SUNPANEL_API_TOKEN=
      - LUCKY_API_ENDPOINT=http://192.168.1.100:16601
      - LUCKY_API_TOKEN=
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./bookmarks_history:/app/bookmarks_history
```

## 环境变量配置

在 `.env` 文件中配置以下环境变量：

```bash
# SunPanel API 配置
SUNPANEL_API_BASE=http://your-sunpanel-ip:3002/openapi/v1
SUNPANEL_API_TOKEN=your_sunpanel_token

# Lucky API 配置
LUCKY_API_ENDPOINT=http://your-lucky-ip:16601
LUCKY_API_TOKEN=your_lucky_token
```

## 部署方式

### 使用 Docker Compose (推荐)

1. 修改 `docker-compose.yml` 中的环境变量配置
2. 运行以下命令启动服务：

```bash
docker-compose up -d
```

### 手动部署

1. 安装依赖：
```bash
pip install -r requirements.txt
```

2. 配置环境变量
3. 运行应用：
```bash
python app.py
```

## 使用方法

1. 访问 `http://localhost:3003` 打开应用界面
2. 在 "Docker / Lucky" 标签页中查看服务列表
3. 点击服务条目中的"添加"按钮将服务导入 Sun-Panel
4. 在 "书签导入" 标签页中上传浏览器书签 HTML 文件
5. 选择文件夹分类查看书签
6. 点击书签条目中的"添加"按钮将书签导入 Sun-Panel

## 使用截图

<img alt="PixPin_2025-09-09_20-43-14" src="https://github.com/user-attachments/assets/74f9f4a3-42ff-41ae-b686-67bbf7bdb8da" />
<img alt="PixPin_2025-09-09_20-43-51" src="https://github.com/user-attachments/assets/31b1ad9c-bfa5-483a-9da7-7aef6dbb1fa7" />
<img alt="PixPin_2025-09-09_20-44-27" src="https://github.com/user-attachments/assets/dcc48bf3-c83b-4f9d-9727-12396bdb37b9" />


## API 接口

- `/api/get_icon_urls?url=` - 获取网站图标 URL
- `/api/sunpanel/groups` - 获取 Sun-Panel 分组列表
- `/api/sunpanel/item/create` - 创建 Sun-Panel 项目
- `/api/bookmarks/upload` - 上传书签文件
- `/api/bookmarks/history` - 获取书签文件历史记录
- `/api/bookmarks/load/<filename>` - 加载历史书签文件

## 依赖项

- Flask: Web 框架
- Requests: HTTP 请求库
- Docker: Docker SDK
- BeautifulSoup4: HTML 解析库
- python-dotenv: 环境变量加载
- lxml: XML/HTML 解析器

## 注意事项

1. 确保 Docker Socket 挂载正确以获取容器信息
2. 确保网络连接正常以访问 Sun-Panel 和 Lucky API
3. 书签文件需要是浏览器导出的标准 HTML 格式
