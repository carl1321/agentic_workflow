# Nginx 配置排查指南

## 1. 查看详细错误信息

```bash
# 查看 Nginx 状态
sudo systemctl status nginx.service

# 查看详细错误日志
sudo journalctl -xeu nginx.service

# 测试配置文件语法
sudo nginx -t
```

## 2. 常见问题及解决方案

### 问题1：配置文件语法错误

**检查方法：**
```bash
sudo nginx -t
```

**常见错误：**
- 缺少分号 `;`
- 括号不匹配
- 路径中的空格没有加引号

### 问题2：路径不存在

**检查方法：**
```bash
# 检查前端构建目录是否存在
ls -la /path/to/web/dist

# 如果不存在，需要先构建前端
cd /path/to/web
npm run build
```

**解决方案：**
- 确保 `root` 路径指向正确的前端构建目录
- Next.js 项目通常是 `web/.next/standalone` 或 `web/out`
- 或者使用 `web/dist`（如果配置了输出目录）

### 问题3：端口被占用

**检查方法：**
```bash
# 检查 8889 端口是否被占用
sudo netstat -tulpn | grep 8889
# 或
sudo lsof -i :8889
```

**解决方案：**
- 如果端口被占用，可以：
  1. 停止占用端口的服务
  2. 或者修改 Nginx 监听端口

### 问题4：权限问题

**检查方法：**
```bash
# 检查 Nginx 用户是否有权限访问目录
sudo -u www-data ls /path/to/web/dist
```

**解决方案：**
```bash
# 给 Nginx 用户添加读取权限
sudo chmod -R 755 /path/to/web/dist
sudo chown -R www-data:www-data /path/to/web/dist
```

### 问题5：配置文件位置错误

**正确的配置文件位置：**
- Ubuntu/Debian: `/etc/nginx/sites-available/` 和 `/etc/nginx/sites-enabled/`
- CentOS/RHEL: `/etc/nginx/conf.d/`

**正确的配置方式：**
```bash
# 1. 创建配置文件
sudo nano /etc/nginx/sites-available/agenticworkflow

# 2. 将配置内容粘贴进去

# 3. 创建软链接（启用配置）
sudo ln -s /etc/nginx/sites-available/agenticworkflow /etc/nginx/sites-enabled/

# 4. 测试配置
sudo nginx -t

# 5. 重启 Nginx
sudo systemctl restart nginx
```

## 3. 完整的正确配置示例

```nginx
server {
    listen 8889;
    server_name 122.193.22.114;

    # 前端静态文件目录（需要修改为实际路径）
    root /var/www/agenticworkflow/web/dist;
    index index.html;

    # 前端静态文件
    location / {
        try_files $uri $uri/ /index.html;
    }

    # 后端 API 代理
    location /api/ {
        proxy_pass http://localhost:8008/api/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        
        # 超时设置
        proxy_connect_timeout 600s;
        proxy_send_timeout 600s;
        proxy_read_timeout 600s;
    }
}
```

## 4. 如果直接修改了 nginx.conf

**注意：** 如果你直接修改了 `/etc/nginx/nginx.conf`，需要确保：

1. **不要删除原有的配置**，应该在 `http {}` 块内添加 `include` 语句：
```nginx
http {
    # ... 其他配置 ...
    
    # 包含站点配置
    include /etc/nginx/sites-enabled/*;
}
```

2. **或者** 在 `http {}` 块内直接添加 `server {}` 块

3. **推荐方式**：使用 `sites-available` 和 `sites-enabled` 目录管理配置

## 5. 快速排查步骤

```bash
# 步骤1：测试配置语法
sudo nginx -t

# 步骤2：如果语法错误，查看具体错误信息
# 根据错误信息修复

# 步骤3：检查路径是否存在
ls -la /path/to/web/dist

# 步骤4：检查端口是否被占用
sudo lsof -i :8889

# 步骤5：检查权限
sudo -u www-data ls /path/to/web/dist

# 步骤6：查看详细日志
sudo tail -f /var/log/nginx/error.log
```




