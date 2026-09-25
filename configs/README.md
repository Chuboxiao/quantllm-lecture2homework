# 本地配置

账号配置存放在 `configs/local/`（Git 忽略），无账号密码的格式样例放在本目录。

参照 [simnow.example.json](simnow.example.json)，填写 `userid`、`password`、`brokerid`、`td_address`、`md_address`、`appid`、`auth_code`；`environment` 保持 `simnow`。环境标签不是服务器地址校验，地址须由使用者确认属于 SimNow。

当前本地 `configs/local/simnow.json` 已切换为用户提供的个人 SimNow 配置，文件权限为 600。账号资料来自用户截图和消息，未读取浏览器密码。不要把本地配置上传到 GitHub。
