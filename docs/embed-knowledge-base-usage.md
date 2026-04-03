# Embedding Index Usage

`embed_knowledge_base.py` 用于把 `articles/reviewed/` 和 `articles/high-value/` 中的知识块写入本地 Chroma 向量库。

## 默认行为

- 项目根目录作为 `kb_root`
- 默认索引 `reviewed,high-value`
- 默认向量库存储到 `vector_store/`
- 默认读取项目根目录的 `zhipu_api_key.txt`
- 默认用文章内容指纹做增量索引

## 常用命令

```bash
python embed_knowledge_base.py
python embed_knowledge_base.py --dry-run
python embed_knowledge_base.py --force
python embed_knowledge_base.py --source-dir reviewed,high-value
```

## 增量逻辑

- 若 `article.md` 内容和索引版本未变化，则跳过
- 若文章内容变化，则先删除该文章旧块，再重建新块
- `--force` 会忽略内容指纹，强制重建

## 失败清单

索引失败的文章会写入：

```text
sources/processed/embed_failures.txt
```

每行格式：

```text
<article_dir>\t<error_message>
```
