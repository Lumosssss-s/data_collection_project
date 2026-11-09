# 模型目录（不参与版本控制）

后端启动时会从 `MEDICAL_MODELS_DIR`（默认 `./models`）加载两个本地模型。权重合计约 **4.28 GB**，
超过 GitHub 单文件 100 MB 限制，因此**不随仓库分发**，需按本文档自行下载。

| 目录 | 模型 | 用途 | 体积（实测） |
|---|---|---|---:|
| `models/bge-m3/` | [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) | 稠密向量嵌入（1024 维） | 2.14 GB |
| `models/bge-reranker-v2-m3/` | [BAAI/bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) | 两阶段精排（cross-encoder） | 2.14 GB |

## 一、一条命令下载

```powershell
# 从仓库根执行；默认走 HuggingFace 官方源
powershell -ExecutionPolicy Bypass -File .\scripts\fetch_models.ps1

# 国内网络建议加 -Mirror（走 hf-mirror.com 镜像）
powershell -ExecutionPolicy Bypass -File .\scripts\fetch_models.ps1 -Mirror
```

脚本会做三件事：下载两个模型到 `./models`、删除 `bge-m3/onnx/`（2.18 GB，本项目的
`SentenceTransformer` 走 PyTorch 权重，不读 ONNX 目录）、按下方清单校验文件是否齐全。

前置依赖：

```powershell
pip install -U huggingface_hub
```

## 二、手工放置

若无法联网，请从可访问的机器下载后拷贝成如下结构（目录名必须一致）：

```text
models/
├── bge-m3/
│   ├── pytorch_model.bin             2165.9 MB
│   ├── tokenizer.json                  16.3 MB
│   ├── sentencepiece.bpe.model          4.8 MB
│   ├── colbert_linear.pt                2.0 MB
│   ├── config.json
│   ├── config_sentence_transformers.json
│   ├── modules.json
│   ├── sentence_bert_config.json
│   ├── special_tokens_map.json
│   ├── tokenizer_config.json
│   └── 1_Pooling/config.json
└── bge-reranker-v2-m3/
    ├── model.safetensors             2165.9 MB
    ├── tokenizer.json                  16.3 MB
    ├── sentencepiece.bpe.model          4.8 MB
    ├── config.json
    ├── special_tokens_map.json
    └── tokenizer_config.json
```

**不要**拷贝 `bge-m3/onnx/`（2.18 GB，本仓库不读取）。

## 三、校验

```powershell
python -c "import os;d='models';req={'bge-m3':['pytorch_model.bin','tokenizer.json','sentencepiece.bpe.model','config.json'],'bge-reranker-v2-m3':['model.safetensors','tokenizer.json','sentencepiece.bpe.model','config.json']};[print(k,[(f,os.path.exists(os.path.join(d,k,f))) for f in v]) for k,v in req.items()]"
```

启动后以 `/health/ready` 为准，返回 `{"models":{"reranker":"loaded","embedding":"loaded"}}` 即加载成功
（判定逻辑见 `medical_rag/main.py`）。缺少权重时 backend 一直停留在 503。

## 四、为什么不用 Git LFS / Release 附件

`pytorch_model.bin` 与 `model.safetensors` 各 2.17 GB：Git LFS 免费额度 1 GB，GitHub Release
单文件上限 2 GB，两者都装不下。因此仓库只保留本文档，权重走下载或离线包。
