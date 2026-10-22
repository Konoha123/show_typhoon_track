"""Web 服务简单入口：python app.py（监听 host/port 读 configs/server.json，缺文件报错退出）。"""

import uvicorn

from typhoon_track.api.server_config import ServerConfig

config = ServerConfig.load()
uvicorn.run("typhoon_track.api.app:app", host=config.host, port=config.port)
