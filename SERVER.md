


## VLLM启动openai 接口
```
cd /data2/cc/LLM-VL
conda activate vllm
export CUDA_VISIBLE_DEVICES="2,3" 
vllm serve Qwen3.5-9B -dp 2 --gpu-memory-utilization 0.85  --max-model-len 262144 --max-num-seqs 256 --reasoning-parser qwen3  --performance-mode throughput --max_num_batched_tokens 16384  --mm-encoder-tp-mode data --reasoning-config '{"reasoning_start_str": "<think>", "reasoning_end_str": "I have to give the solution based on the reasoning directly now.</think>"}'
```

## EmbodiedBench评测

<!-- conda activate omniagent -->

1. EmbodiedBench已经clone到/home/zzz/vla_code/OmniRoboAgent/benchmarks/EmbodiedBench,然后评测集合使用EB-ALFRED
2. 仅在测试 EB-ALFRED 时从 `omniagent` clone `omniagent-eb`，再按照根目录 `README.md` 使用 `uv` 安装 `eb-alfred` extra；不要将 benchmark 依赖安装到 `omniagent`
3. LLM使用 VLLM启动openai 接口,我已经启动在http://127.0.0.1:8000,如果挂掉了可以使用VLLM启动openai 接口的方法重新启动
