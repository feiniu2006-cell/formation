# 打包说明

## 打包脚本分析

### 📦 脚本功能

`build_check_multilang_exe.py` 是一个加密打包脚本，功能如下：

1. **加密保护**：使用 Fernet 加密主脚本和数据库配置
2. **独立运行**：打包成单一EXE文件，无需Python环境
3. **GUI模式**：`console=False` 配置为窗口程序

### 🔧 工作原理

```
check_multilang_folder.py  ──┐
                        ├─> 加密 ──> launcher.py ──> PyInstaller ──> EXE
db_config.py  ────────────────┘
```

### 📋 依赖检查

#### 快速检查依赖

```bash
python -c "import cryptography, PyInstaller, pymysql, translators, requests; print('所有依赖已安装')"
```

所需依赖：
- ✅ cryptography - 加密库
- ✅ PyInstaller - 打包工具  
- ✅ pymysql - 数据库驱动
- ✅ translators - 翻译库
- ✅ requests - HTTP库

### 🚀 打包步骤
#### 1. 确保所有依赖已安装

```bash
pip install cryptography pyinstaller pymysql translators requests
```

## 2. 确保必要文件存在

- ✅ `check_multilang_folder.py` - 主脚本
- ✅ `../db_config.py` - 数据库配置（在父目录）

#### 3. 运行打包脚本

```bash
python build_check_multilang_exe.py
```

#### 4. 输出位置

打包完成后，EXE文件位于：
```
dist_encrypted/check_multilang_folder.exe
```

### 📁 生成的目录结构

```
check_language/
├── build_encrypted/                # 构建目录
│   ├── check_multilang_encrypted_launcher.py  # 加密启动器
│   ├── check_multilang_folder.spec      # PyInstaller配置
│   └── pyinstaller_work/                      # 临时构建文件
│
└── dist_encrypted/                    # 输出目录
    └── check_multilang_folder.exe        # ✨ 最终EXE文件
```

### ⚙️ 打包配置

#### 加密方式
- 使用 `cryptography.fernet.Fernet` 对称加密
- 每次打包生成新的随机密钥
- 密钥嵌入到启动器中

#### PyInstaller 配置
- **模式**：单文件模式（`onefile`）
- **控制台**：禁用（`console=False`）- GUI窗口模式
- **压缩**：启用UPX压缩（`upx=True`）
- **优化**：无优化（`optimize=0`）

#### 隐藏导入
自动收集以下模块的所有子模块：
- pymysql
- requests
- translators

### 🔍 常见问题

#### 问题1：找不到 db_config.py

**错误**：
```
FileNotFoundError: 未找到公共数据库配置
```

**解决**：
确保 `db_config.py` 位于父目录：
```
数据处理/
├── db_config.py      ← 这里
└── check_language/
    └── build_check_multilang_exe.py
```

#### 问题2：缺少依赖

**错误**：
```
ModuleNotFoundError: No module named 'XXX'
```

**解决**：
```bash
python check_deps.py  # 检查缺少哪些依赖
pip install <missing_package>
```

#### 问题3：打包后运行出错

**可能原因**：
1. 数据库配置加密有问题
2. 缺少运行时依赖
3. 路径问题

**调试方法**：
修改 `.spec` 文件，临时启用控制台查看错误：
```python
console=True,  # 改为 True
```

### 📊 打包大小

预期EXE文件大小：**约 30-50 MB**

包含：
- Python解释器
- tkinter GUI库
- pymysql、requests、translators库
- 加密的主脚本和配置

### 🔒 安全说明

1. **加密保护**：源代码加密，无法直接反编译查看
2. **数据库配置**：敏感配置也被加密
3. **密钥安全**：密钥嵌入EXE，提供一定程度保护

⚠️ **注意**：这不是军事级加密，有经验的逆向工程师仍可能提取代码

### 🎯 使用建议

#### 开发阶段
- 直接运行 Python 脚本：`python check_multilang_folder.py`
- 方便调试和修改

#### 分发阶段
- 打包成 EXE 分发给不懂Python的用户
- 双击即可运行，无需配置环境

### 📝 修改打包配置

如果需要修改打包设置，编辑 `build_check_multilang_exe.py` 中的 `write_spec()` 函数：

```python
exe = EXE(
    ...
    console=False,      # True=显示控制台，False=隐藏控制台
    upx=True,           # True=启用压缩，False=禁用压缩
    ...
)
```

### ✅ 验证打包结果

打包完成后，测试EXE：

1. 双击 `dist_encrypted/check_multilang_folder.exe`
2. 应该弹出GUI界面
3. 尝试进行一次检测
4. 查看是否正常工作

---

**文件检查清单**：
- [ ] check_multilang_folder.py 存在且无语法错误
- [ ] ../db_config.py 存在且配置正确
- [ ] 所有依赖已安装（运行 check_deps.py）
- [ ] Python 版本 >= 3.7

**打包成功标志**：
```
打包完成: C:\Users\Admin\Desktop\数据处理\check_language\dist_encrypted\check_multilang_folder.exe
```

---

**最后更新**：2026-06-02
