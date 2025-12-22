# 密码存储机制说明

## 概述

系统采用**多层安全机制**保护用户密码：

1. **传输层**：RSA-OAEP 加密（前端 → 后端）
2. **存储层**：bcrypt 单向哈希（数据库存储）

## 数据库层面密码存储

### 表结构

`users` 表中的 `password_hash` 字段用于存储密码哈希值：

```sql
-- 建议的表结构（PostgreSQL）
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(255) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,  -- 存储 bcrypt 哈希值
    -- ... 其他字段
);
```

**字段说明**：
- **类型**：`VARCHAR(255)` 或 `TEXT`
- **长度**：bcrypt 哈希值固定为 **60 字符**
- **格式**：`$2b$12$<salt><hash>`（bcrypt 标准格式）

### bcrypt 哈希格式

bcrypt 哈希值示例：
```
$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYq5q5q5q5q
```

格式解析：
- `$2b$`：算法标识符（bcrypt 版本）
- `12`：cost factor（计算轮数，2^12 = 4096 次迭代）
- 后续 53 字符：salt（22 字符）+ hash（31 字符）

### 存储流程

#### 1. 创建用户时

```python
# src/server/auth/admin/users.py
password_hash = hash_password(password)  # 使用 bcrypt 哈希
cursor.execute(
    "INSERT INTO users (username, email, password_hash, ...) VALUES (%s, %s, %s, ...)",
    (username, email, password_hash, ...)
)
```

#### 2. 修改密码时

```python
# src/server/auth/admin/users.py
password_hash = hash_password(new_password)  # 重新哈希
cursor.execute(
    "UPDATE users SET password_hash = %s WHERE id = %s",
    (password_hash, user_id)
)
```

#### 3. 验证密码时

```python
# src/server/auth/routes.py
password_hash = user_data.get("password_hash")  # 从数据库读取
verify_password(password, password_hash)  # 使用 bcrypt 验证
```

### 哈希算法实现

**文件**：`src/server/auth/password.py`

```python
def hash_password(password: str) -> str:
    """
    使用 bcrypt 哈希密码。
    
    如果 bcrypt 不可用，回退到不安全的纯文本存储（仅用于开发调试）。
    """
    if bcrypt is not None:
        salt = bcrypt.gensalt()  # 自动生成随机 salt
        hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
        return hashed.decode("utf-8")  # 返回 60 字符的哈希值
    # 开发环境回退（不安全）
    return f"plain${password}"

def verify_password(password: str, password_hash: str) -> bool:
    """
    验证密码是否匹配哈希值。
    """
    if password_hash.startswith("plain$"):
        # 回退模式（仅开发）
        return password_hash == f"plain${password}"
    
    # 使用 bcrypt 验证
    return bcrypt.checkpw(
        password.encode("utf-8"),
        password_hash.encode("utf-8")
    )
```

### 安全特性

#### ✅ bcrypt 的优势

1. **随机 Salt**：每次哈希都使用不同的随机 salt，相同密码产生不同哈希值
2. **自适应成本**：可通过 `cost factor` 调整计算强度（默认 12，约 4096 次迭代）
3. **单向哈希**：无法逆向，只能通过暴力破解
4. **抗彩虹表**：随机 salt 使彩虹表攻击无效

#### ✅ 存储安全

- **不存储明文**：数据库永远不存储原始密码
- **固定长度**：所有哈希值都是 60 字符，无法通过长度推断密码
- **不可逆**：即使数据库泄露，也无法直接获取原始密码

### 数据库字段建议

```sql
-- PostgreSQL 推荐配置
ALTER TABLE users 
    ALTER COLUMN password_hash TYPE VARCHAR(255) NOT NULL;

-- 添加索引（如果需要按密码哈希查询，但通常不需要）
-- 注意：不建议对 password_hash 建立索引，因为：
-- 1. 密码验证通过 username 查找用户，不需要密码哈希索引
-- 2. 索引可能泄露密码哈希值的使用模式
```

### 迁移现有密码

如果现有系统使用其他哈希算法，可以编写迁移脚本：

```python
# 迁移脚本示例
def migrate_passwords():
    """将旧密码哈希迁移到 bcrypt"""
    users = get_all_users()
    for user in users:
        old_hash = user['password_hash']
        if not old_hash.startswith('$2b$'):  # 不是 bcrypt 格式
            # 提示用户重新设置密码，或使用临时密码
            # 新密码会在用户首次登录时更新
            pass
```

### 生产环境检查清单

- [ ] 确保 `bcrypt` 包已安装：`pip install bcrypt`
- [ ] 检查所有密码哈希都是 bcrypt 格式（以 `$2b$` 开头）
- [ ] 移除所有 `plain$` 前缀的密码（开发环境遗留）
- [ ] 设置合适的 `cost factor`（建议 12-14，平衡安全性和性能）
- [ ] 定期审计密码哈希格式
- [ ] 考虑实施密码策略（最小长度、复杂度要求）

### 性能考虑

- **bcrypt 计算成本**：每次哈希/验证需要约 100-200ms（cost=12）
- **数据库查询**：密码验证通过 `username` 索引查找，性能良好
- **并发处理**：bcrypt 是 CPU 密集型操作，高并发时考虑限流

### 示例：完整的密码存储流程

```
用户输入密码: "MySecurePassword123"
    ↓
前端 RSA 加密: "base64_encrypted_string..."
    ↓
后端 RSA 解密: "MySecurePassword123"
    ↓
bcrypt 哈希: "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYq5q5q5q5q"
    ↓
存储到数据库: password_hash = "$2b$12$..."
```

### 相关文件

- `src/server/auth/password.py` - 密码哈希和验证
- `src/server/auth/admin/users.py` - 用户创建/更新（使用哈希）
- `src/server/auth/routes.py` - 登录验证（使用哈希）
- `src/server/auth/crypto.py` - RSA 加密/解密（传输层）

