#!/bin/bash
# Nginx 配置脚本 - 使用 sites-available 方式

echo "=== Nginx 配置指南 ==="
echo ""
echo "请按照以下步骤操作："
echo ""
echo "1. 创建配置文件："
echo "   sudo nano /etc/nginx/sites-available/agenticworkflow"
echo ""
echo "2. 将以下配置内容粘贴进去（记得修改 root 路径）："
echo ""
cat << 'EOF'
server {
    listen 8889;
    server_name 122.193.22.114;

    # 前端静态文件目录（需要修改为实际路径）
    # Next.js 构建后的目录，通常是 web/.next/standalone 或 web/out
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
        
        # 超时设置（用于长时间运行的工作流）
        proxy_connect_timeout 600s;
        proxy_send_timeout 600s;
        proxy_read_timeout 600s;
    }
}
EOF
echo ""
echo "3. 创建软链接启用配置："
echo "   sudo ln -s /etc/nginx/sites-available/agenticworkflow /etc/nginx/sites-enabled/"
echo ""
echo "4. 测试配置："
echo "   sudo nginx -t"
echo ""
echo "5. 如果测试通过，重启 Nginx："
echo "   sudo systemctl restart nginx"
echo ""
echo "6. 检查状态："
echo "   sudo systemctl status nginx"
echo ""




