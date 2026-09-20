# Memory 组件说明

本目录包含 OmniRoboAgent 的记忆接口与实现。空间记忆采用组件化方式接入：
`SpatialMemory` 只负责空间地图和空间布局定位，应用侧通过 `CompositeMemory` 将它与
事件记忆、工作记忆等其他组件组合，不需要把空间逻辑接入 Planner、Verifier 或
Pipeline。

## 组件分工

| 组件 | 职责 | `recall()` 输出 |
| --- | --- | --- |
| `TieredMemory` | 工作帧、近期事件、关键事件、摘要 | `working_frames`、`recent_events`、`key_events`、`summary` |
| `SpatialMemory` | RGB-D 关键帧筛选、反投影、体素点云融合、空间布局定位 | 仅 `spatial` localization |
| `CompositeMemory` | 转发生命周期调用并合并多个记忆组件的结果 | 所有子组件结果的组合 |

`SpatialMemory` 不提供空的事件列表或摘要，也不把点云、轨迹、帧计数、PLY 路径等
日志信息放入记忆上下文。这样下游读取 `recall()` 时只会获得可直接使用的空间布局
定位结果。

## 通过 CompositeMemory 使用

推荐由业务代码持有并调用 `CompositeMemory`：

```python
from omniroboagent.agent_core.memories import (
    CompositeMemory,
    SpatialMemory,
    TieredMemory,
)

memory = CompositeMemory(
    memories={
        "episodic": TieredMemory(),
        "spatial": SpatialMemory(
            voxel_size_m=0.03,
            pixel_stride=8,
            keyframe_translation_m=0.05,
            keyframe_rotation_deg=5.0,
            artifact_dir="artifacts/spatial",
            session_export_interval_keyframes=10,
        ),
    }
)

memory.reset("session-1")
memory.update(state, event)
memory_context = memory.recall({"session_id": "session-1"})
localization = memory_context["spatial"]
```

配置文件可以使用嵌套的 `class_path`：

```yaml
memory:
  class_path: omniroboagent.agent_core.memories.CompositeMemory
  init_args:
    memories:
      episodic:
        class_path: omniroboagent.agent_core.memories.TieredMemory
      spatial:
        class_path: omniroboagent.agent_core.memories.SpatialMemory
        init_args:
          voxel_size_m: 0.03
          pixel_stride: 8
          keyframe_translation_m: 0.05
          keyframe_rotation_deg: 5.0
          artifact_dir: artifacts/spatial
          session_export_interval_keyframes: 10
          spatial_backend:
            class_path: omniroboagent.backends.spatial.SpatialLMBackend
            init_args:
              model_path: <MODEL_PATH>
              default_wall_thickness: 0.12
              output_precision: 6
          spatial_detect_type: all
          spatial_seed: 42
```

`CompositeMemory.update()` 会把同一份 `state` 和 `event` 分发给所有子组件；每个
组件只消费自己需要的字段。`CompositeMemory.recall()` 会保留事件记忆的标准字段，
并把 `SpatialMemory` 返回的 `spatial` localization 合并到同一个上下文中。

## RGB-D 输入协议

空间帧从 observation 的 `spatial_frames` 字段进入。它可以是一帧，也可以是帧序列：

```python
state = {
    "observation": {
        "spatial_frames": [spatial_frame],
    }
}
memory.update(state, event={})
```

如果最新 observation 位于执行结果中，也可以使用：

```python
event = {
    "environment_result": {
        "observation": {
            "spatial_frames": [spatial_frame],
        }
    }
}
memory.update(state, event)
```

单帧结构如下：

```python
spatial_frame = {
    "timestamp_ns": 1_725_000_000_000_000_000,
    "camera_id": "head_camera",
    "frame_id": "head_camera_optical_frame",
    "world_frame": "map",
    "rgb": rgb,        # H x W x 3，RGB，取值 0..255
    "depth_m": depth,  # H x W，单位为 m
    "intrinsics": {
        "width": 640,
        "height": 480,
        "fx": 615.0,
        "fy": 615.0,
        "cx": 319.5,
        "cy": 239.5,
    },
    "T_world_camera": [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 1.2],
        [0.0, 0.0, 0.0, 1.0],
    ],
}
```

输入约束：

- RGB 与深度必须已经完成时间同步、像素对齐和去畸变。
- `depth_m` 必须使用米；超出 `depth_min_m` 和 `depth_max_m` 的值会被忽略。
- RGB、深度尺寸必须与内参中的 `width`、`height` 一致。
- `T_world_camera` 是绝对刚体变换，满足
  `point_world = T_world_camera @ point_camera`。
- `world_frame` 必须等于 `SpatialMemory.map_frame`，默认值为 `map`。
- 位姿估计、相机与机器人基座的外参链计算不属于 Memory，应由上游 integration 提供。

## 关键帧与地图更新

数据处理流程为：

```text
RGB-D + intrinsics + T_world_camera
  -> 输入校验
  -> 关键帧判定
  -> 深度反投影
  -> 转换到 map_frame
  -> voxel 点云融合
  -> 将当前内存点云转为 Z-up points/colors
  -> SpatialLMBackend.infer_points()
  -> 每 10 个关键帧按需导出 session checkpoint
  -> 更新 recall() 可见结果
```

每个相机的第一帧是关键帧。后续帧相对上一关键帧满足任一条件时才更新地图：

- 平移达到 `keyframe_translation_m`；
- 旋转达到 `keyframe_rotation_deg`；
- 两个阈值都设置为 `0`，表示每个有效帧都是关键帧。

没有达到阈值的帧只记录轨迹，不融合地图；没有有效深度的帧也不会融合。每次关键帧
成功完成体素融合和 map revision 更新后，如果配置了 `spatial_backend`，会同步调用
一次 `update_layout()`。`update_layout()` 默认通过 `point_cloud()` 取得当前内存
点云，也可以显式接收同结构 mapping、`.ply` 路径、裸 XYZ 数组或 packed
XYZRGB(A)。mapping/数组输入在 `_localize_with_spatiallm()` 内按
`(x, y, z) -> (x, z, -y)` 转为 `+X` 向右、`+Y` 向前、`+Z` 向上，且不会修改原
输入；外部 PLY 默认已经是 Z-up，解析为 points/colors 后不会再次旋转。所有路径
最终统一调用 `SpatialLMBackend.infer_points()`；普通帧不会触发 SpatialLM。

`SpatialLMBackend` 在 Memory lifecycle 内长期复用，由 `SpatialMemory.close()` 释放。
未配置 backend 时建图、轨迹和 artifact 导出继续工作，但显式 `update_layout()` 会
抛出错误。外部 PLY 支持 ASCII 与 binary little-endian PLY 1.0，vertex 必须包含
`x/y/z`，颜色 `red/green/blue[/alpha]` 可选。

## Recall 契约

`SpatialMemory.recall()` 仅返回最新 localization：

```python
{
    "spatial": {
        "walls": [...],
        "doors": [...],
        "windows": [...],
        "objects": [...],
    }
}
```

其中墙、门、窗和物体使用 backend 校验后的 JSON-compatible SpatialLM schema。
`recall()` 不附加点云、轨迹或推理 metadata，只暴露最近一次成功推理结果；backend
未配置或当前 session 尚未完成推理时，这四个集合均为空。

## 点云、轨迹与日志

以下内容用于调试、持久化或运行观测，不会进入 `recall()`：

- `point_cloud()`：返回当前 map revision 的点坐标与 RGB 颜色；
- `trajectory()`：返回每帧内参、`T_world_camera`、关键帧标记和融合状态，不保存原始 RGB-D；
- `export_ply()`：将当前点云转换为 Z-up 后原子写为 binary PLY；
- `export_session()`：导出同一 revision 的 PLY 与 JSON session manifest；配置了
  `artifact_dir` 时默认每 10 个成功融合关键帧自动调用一次；
- `healthcheck()`：返回实现类型、点数、map revision、轨迹帧数和最近一次自动导出路径。

在线地图的权威状态是内存中的 voxel 点云，而不是 PLY。新关键帧直接融合到已有
voxel；PLY 只是按需导出的快照，不应该在每一帧重新读取并作为地图累积来源。
`spatial_session.json` 使用 `point_cloud_coordinate_convention` 记录 PLY 的
`x_right_y_forward_z_up` 约定；在线 voxel map、轨迹和 `T_world_camera` 不随 PLY
artifact 旋转。

自动 checkpoint 由 `session_export_interval_keyframes` 控制，默认值是 `10`：

- 设置了 `artifact_dir`：在第 10、20、30……个成功融合关键帧后自动导出；
- `artifact_dir=None`：保持纯内存运行，不自动落盘；
- `session_export_interval_keyframes=None`：即使设置了 `artifact_dir` 也禁用自动导出；
- 仍可在 session 结束、异常排查或手动 checkpoint 时显式调用 `export_session()`。

自动导出的 PLY 使用 revision 文件名，例如 `map_000010.ply`、`map_000020.ply`；
`spatial_session.json` 始终表示最近一次 checkpoint。

## 主要参数

| 参数 | 默认值 | 说明 |
| --- | ---: | --- |
| `frame_buffer_size` | `32` | 内部保留的最近输入帧数量 |
| `frame_key` | `spatial_frames` | observation 中的空间帧字段名 |
| `map_frame` | `map` | 全局点云坐标系 |
| `voxel_size_m` | `0.03` | voxel 边长，单位 m |
| `depth_min_m` | `0.2` | 最小有效深度 |
| `depth_max_m` | `5.0` | 最大有效深度 |
| `pixel_stride` | `8` | 反投影像素采样步长 |
| `max_voxel_weight` | `20` | 单个 voxel 的最大融合权重 |
| `keyframe_translation_m` | `0.05` | 关键帧平移阈值 |
| `keyframe_rotation_deg` | `5.0` | 关键帧旋转阈值 |
| `artifact_dir` | `None` | 默认 PLY 和 session manifest 输出目录 |
| `session_export_interval_keyframes` | `10` | 自动导出 session checkpoint 的关键帧间隔；`None` 表示禁用 |
| `spatial_backend` | `None` | 可选、长期复用的 `SpatialLMBackend`；未配置时不自动推理 |
| `spatial_detect_type` | `all` | `all`、`arch` 或 `object` |
| `spatial_seed` | `42` | SpatialLM generation seed |

## 当前边界

- 当前重建表示为增量 voxel 点云，不包含 TSDF、网格生成或表面补洞。
- 当前不包含回环检测、位姿图优化和历史地图重融合；外参误差会累积到地图中。
- 当前不进行动态物体过滤、多相机同步或 RGB-depth registration。
- SpatialLM 在每个成功融合关键帧后同步运行，尚未实现异步推理、队列或频率控制。
- 真实 checkpoint 的 GPU 显存、延迟和长 session 稳定性尚未完成 smoke 验证。
- 反投影使用不依赖 NumPy/Open3D 的通用实现；高分辨率实时场景可在保持输入与
  `recall()` 契约不变的情况下替换为 NumPy、Open3D 或 CUDA 后端。
