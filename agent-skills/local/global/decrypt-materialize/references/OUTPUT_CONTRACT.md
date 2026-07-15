# Output Contract

## Naming

每个导出的工作表对应一个输出文件。

文件名模式：

`<workbook_name>_<sheet_name>_<YYYYMMDD>.csv`

规则：
- `<workbook_name>`：工作簿文件名（去除扩展名）
- `<sheet_name>`：工作表名称，清理特殊字符（`/` `\` 替换为 `_`），可选转为 `snake_case`
- `<YYYYMMDD>`：日期标签，8 位数字
- **使用单个下划线 `_` 分隔**，不使用双下划线 `__`
- 写入到调用者指定的输出目录
- 永不覆盖源工作簿

示例：
- `Q2_Sales.numbers` 的 `Summary` 工作表 → `Q2_Sales_Summary_20260713.csv`
- `产品数据.xlsx` 的 `商品信息` 工作表 → `产品数据_商品信息_20260713.csv`

## Normalization

将以下值写为空字符串：
- 真实的空单元格
- Excel 错误单元格：`#N/A`, `#REF!`, `#VALUE!`, `#DIV/0!`, `#NAME?`, `#NUM!`, `#NULL!`
- 占位符字符串（trim 后）：`NULL`, `null`, `None`, `none`, `NaN`, `nan`

保持：
- 普通字符串
- 数值
- 原始行顺序
- 原始列顺序

## Verification

对每个生成的 CSV，验证：
- 文件存在
- header 存在
- 行数匹配源工作表行数
- 列数匹配源工作表列数
- 禁止的占位符值不存在

## Scope Guard

此阶段仅做提取。
除非用户明确扩展范围，否则不要：
- 重命名列
- 推断业务含义
- 去重行
- 重写类别
