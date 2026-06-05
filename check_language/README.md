# 多语言检测与修复工具

## 功能简介

这是一个用于游戏项目多语言文件检测和自动修复的工具，支持17种语言的翻译管理。

## 支持语言

eng(英语)、ind(印尼)、por(葡萄牙)、spa(西班牙)、tha(泰语)、vie(越南)、sch(简中)、tch(繁中)、hin(印地)、ben(孟加拉)、msa(马来)、mya(缅甸)、khm(高棉)、lao(老挝)、tgl(菲律宾)、jpn(日语)、kor(韩语)

## 使用方法

### GUI模式（推荐）

```bash
python check_multilang_folder.py
```

在GUI界面中：
1. 选择扫描范围（VegasGames、MiniGame、公用多语言或全部）
2. 点击"开始检测"查看结果
3. 选择需要修复的游戏，点击"修复选中"或"修复全部"

### 命令行模式

```bash
python check_multilang_folder.py --cli
```

## 检测内容

- ✅ 文件夹和JSON文件是否完整
- ✅ 翻译内容是否正确
- ✅ 占位符（如 %{coins}）是否完整
- ✅ 游戏名称与数据库是否一致
- ✅ 专有术语（Wild、Scatter、Bonus等）保留检查

## 修复功能

1. **文件缺失修复**：自动创建缺失的语言文件夹和JSON文件
2. **翻译内容修复**：调用Google Cloud Translation API自动翻译
3. **数据库同步**：自动更新MySQL数据库中的游戏名称

## 配置说明

### 扫描路径（在脚本中修改）

```python
BASE = Path(r"C:\VegasGames")              # 主游戏目录
MINIGAME = Path(r"C:\VegasGames\MiniGame") # 小游戏目录
COMMON = Path(r"C:\VegasGames\策划\公用多语言")  # 公用文本
```

### 数据库配置

在父目录创建 `db_config.py` 文件：

```python
DATABASE_CONFIGS = {
  "MY": {
        "host": "localhost",
        "port": 3306,
        "user": "root",
        "password": "your_password",
        "database": "your_database"
    }
}
```

### 翻译API配置

在脚本中设置Google Cloud API Key：

```python
GOOGLE_CLOUD_API_KEY = "your_api_key_here"
```

## 打包为EXE

```bash
python build_check_multilang_exe.py
```

生成的EXE文件位于 `dist_encrypted` 目录。

## 依赖项

```bash
pip install pymysql translators requests
```

## 输出

- **检测报告**：`检测报告.txt`（包含详细的检测结果）
- **日志**：GUI界面的"日志"标签页实时显示处理过程

## 注意事项

1. 翻译功能需要Google Cloud Translation API密钥
2. 数据库功能需要配置 `db_config.py`
3. 首次运行建议先使用"文件缺失检测"模式
4. 翻译修复会调用API产生费用，请谨慎使用

## 文件说明

- `check_multilang_folder.py` - 主程序
- `build_check_multilang_exe.py` - 打包脚本
- `检测报告.txt` - 最近一次检测的报告
- `build_encrypted/` - PyInstaller构建目录
- `dist_encrypted/` - 打包后的EXE目录

---

**最后更新**：2026-06-02
