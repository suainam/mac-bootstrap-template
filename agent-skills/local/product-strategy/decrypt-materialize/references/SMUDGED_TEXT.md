# Smudged 文本处理

处理被 git-smudge 过滤器加密的文本文件。

---

## 识别模式

**Smudged 文本的特征**：
1. Read 工具返回乱码/二进制字节
2. 文件扩展名表明应该是文本格式
3. 磁盘上的文件在 git-smudge 过滤器处理后是明文

### 支持的文本格式

任何预期为文本的扩展名：
- 配置文件：`.yaml`, `.yml`, `.toml`, `.json`, `.ini`, `.conf`
- 环境变量：`.env`, `.envrc`
- 属性文件：`.properties`
- 其他文本：`.txt`, `.md`, `.cfg`

---

## 处理流程

### 读取

**绕过 Read 工具**，直接访问磁盘文件：

```bash
# Shell 读取
cat private/secrets.yaml
less private/config.toml

# Python 读取
python3 -c "
with open('private/secrets.yaml') as f:
    print(f.read())
"

# Python 解析
python3 -c "
import yaml
with open('private/secrets.yaml') as f:
    data = yaml.safe_load(f)
    print(data['key'])
"
```

### 编辑

直接编辑磁盘文件，git-clean 过滤器会在提交时自动重新加密：

```bash
# 用编辑器打开（看到的是明文）
vim private/secrets.yaml
nano private/config.toml

# 保存后，git status 会显示文件已修改
# git commit 时，clean 过滤器自动加密
```

### 验证加密状态

```bash
# 检查 git-smudge/clean 配置
git config --get-regexp filter

# 检查 .gitattributes
cat .gitattributes | grep filter

# 查看 Read 工具返回的内容（应该是乱码）
# vs. 磁盘文件内容（应该是明文）
diff <(git show HEAD:private/secrets.yaml) <(cat private/secrets.yaml)
```

---

## 完成标准

- 所需内容被成功读取或编辑
- 无需发明自定义解密路径
- 无需触碰加密字节

---

## 常见错误

### ❌ 错误：尝试"解密"文件

```bash
# 不要这样做
openssl enc -d -aes-256-cbc -in private/secrets.yaml -out decrypted.yaml
```

**原因**：git-smudge 过滤器已经处理了解密，磁盘上就是明文。

### ❌ 错误：用 Read 工具读取后尝试解析

```python
# 不要这样做
encrypted_content = read_tool("private/secrets.yaml")  # 返回乱码
yaml.safe_load(encrypted_content)  # 失败
```

**原因**：Read 工具返回的是加密内容，需要绕过它。

### ✅ 正确：直接访问磁盘文件

```python
# 正确做法
with open("private/secrets.yaml") as f:
    data = yaml.safe_load(f)  # 成功
```

---

## 示例场景

### 场景 1：读取加密的 YAML 配置

```bash
# Read 工具显示乱码
Read("private/database.yaml")  # → 乱码

# 直接读取磁盘文件
cat private/database.yaml
# 输出：
# host: db.internal.com
# port: 5432
# user: admin
```

### 场景 2：更新加密的 TOML 配置

```bash
# 1. 编辑明文文件
vim private/app.toml
# 修改后保存

# 2. git 自动处理加密
git add private/app.toml
git commit -m "更新应用配置"
# clean 过滤器自动加密

# 3. 验证
git show HEAD:private/app.toml  # 显示加密内容
cat private/app.toml  # 显示明文内容
```

### 场景 3：Python 脚本读取加密配置

```python
#!/usr/bin/env python3
"""读取 git-smudge 加密的配置文件"""

import yaml
from pathlib import Path

# 直接读取磁盘文件（已被 smudge 过滤器解密）
config_path = Path("private/secrets.yaml")
with config_path.open() as f:
    config = yaml.safe_load(f)

# 使用配置
service_endpoint = config['service_endpoint']
print(f"Service Endpoint: {service_endpoint}")
```
