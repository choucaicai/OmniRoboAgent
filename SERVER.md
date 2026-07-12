


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
2. EmbodiedBench的环境还未安装,在omniagent基础上,clone这个omniagent环境,得到omniagent-eb,然后按照/home/zzz/vla_code/OmniRoboAgent/benchmarks/EmbodiedBench的教程来安装依赖和环境,然后用这个omniagent-eb来跑
3. LLM使用 VLLM启动openai 接口,我已经启动在http://127.0.0.1:8000,如果挂掉了可以使用VLLM启动openai 接口的方法重新启动

