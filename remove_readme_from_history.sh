#!/bin/bash
# 从 Git 历史记录中删除 README.md 文件

echo "⚠️  警告: 此操作会重写 Git 历史记录"
echo "请确保你已经备份了代码，并且没有其他人正在使用这个仓库"
echo ""
read -p "是否继续? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "操作已取消"
    exit 1
fi

# 方法1: 使用 git filter-branch (适用于所有 Git 版本)
echo "正在从 Git 历史记录中删除 README.md..."
git filter-branch --force --index-filter \
  "git rm --cached --ignore-unmatch README.md" \
  --prune-empty --tag-name-filter cat -- --all

# 清理备份引用
git for-each-ref --format="%(refname)" refs/original/ | xargs -n 1 git update-ref -d

# 强制垃圾回收
git reflog expire --expire=now --all
git gc --prune=now --aggressive

echo "✅ 完成! README.md 已从 Git 历史记录中删除"
echo ""
echo "⚠️  重要提示:"
echo "1. 如果已经推送到远程仓库，需要强制推送:"
echo "   git push origin --force --all"
echo "   git push origin --force --tags"
echo ""
echo "2. 通知所有协作者重新克隆仓库"
