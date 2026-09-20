# SpatialMemory 空间记忆组件

`SpatialMemory` 将全局场景点云或实时 RGB-D 地图转换成结构化空间记忆，为智能体
提供墙体、门窗、物体及其位置等空间上下文。它通过 `recall()` 返回
`memory_context["spatial"]`；`LanguageSkillPlanner` 会把该字段加入模型提示词，使
规划能够同时参考当前视觉、历史记忆和场景空间布局。

空间记忆采用组件化方式接入：`SpatialMemory` 只负责空间地图和空间布局定位，
应用侧通过 `CompositeMemory` 将它与事件记忆、工作记忆等其他组件组合，不需要修改
Pipeline 的 Memory lifecycle。它不负责 SLAM 位姿估计、任务规划、导航或动作执行。

## 组件分工

| 组件 | 职责 | `recall()` 输出 |
| --- | --- | --- |
| `TieredMemory` | 工作帧、近期事件、关键事件、摘要 | `working_frames`、`recent_events`、`key_events`、`summary` |
| `SpatialMemory` | 全局 PLY 单次定位，或 RGB-D 关键帧体素建图与布局定位 | 仅 `spatial` localization |
| `CompositeMemory` | 转发生命周期调用并合并多个记忆组件的结果 | 所有子组件结果的组合 |

`SpatialMemory` 不提供空的事件列表或摘要，也不把点云、轨迹、帧计数、PLY 路径等
日志信息放入记忆上下文。这样下游读取 `recall()` 时只会获得可直接使用的空间布局
定位结果。

## 选择构图方式

`SpatialMemory` 提供两种互斥的空间地图来源：

| 方式 | 如何启用 | 用户必须提供 | observation 要求 |
| --- | --- | --- | --- |
| SLAM 实时构图 | 不配置 `global_scene_ply` | 每帧同步 RGB-D、相机内参和 SLAM/定位系统给出的绝对相机位姿 | 必须在 `frame_key` 指定的字段中提供 frame；默认是 `observation["spatial_frames"]` |
| 全局场景 PLY | 配置 `global_scene_ply` 和 `spatial_backend` | 米制、右手系、Z-up 的完整场景 PLY | 不读取 `spatial_frames`；后续 `update()` 和 `ingest()` 均忽略输入 |

这里的“SLAM 实时构图”表示 `SpatialMemory` 消费上游 SLAM 位姿并增量融合 RGB-D，
不是由 `SpatialMemory` 自己估计相机位姿、回环或重定位。两种方式不能在同一个
`SpatialMemory` 实例中同时使用；只要配置 `global_scene_ply`，就进入全局场景模式。

## 对外接口

```python
from omniroboagent.agent_core.memories.spatial import SpatialMemory
```

| 接口 | 用户侧职责与行为 |
| --- | --- |
| `reset(session_id)` | 开始新 session；在线模式清空地图和轨迹，全局 PLY 模式保留初始化定位结果 |
| `update(state, event)` | 从最新 observation 的 `frame_key` 字段读取一帧或多帧；正常 Agent lifecycle 推荐使用此入口 |
| `ingest(frame)` | 直接提交一帧，适用于 integration 或独立使用；frame 契约与 observation 中完全相同 |
| `recall(query)` | 返回 `{"spatial": {"walls": ..., "doors": ..., "windows": ..., "objects": ...}}` |
| `point_cloud()` / `trajectory()` | 显式读取在线地图或轨迹诊断信息；不进入 `recall()` |
| `export_ply()` / `export_session()` | 导出在线地图的 Z-up PLY 与 session manifest |
| `healthcheck()` | 查看当前模式、地图 revision、点数、artifact 和 backend 状态 |
| `close()` | 释放长期复用的 `SpatialLMBackend` |

## 通过 CompositeMemory 使用

推荐由业务代码持有并调用 `CompositeMemory`：

```python
from omniroboagent.agent_core.memories import TieredMemory
from omniroboagent.agent_core.memories.composite import CompositeMemory
from omniroboagent.agent_core.memories.spatial import SpatialMemory
from omniroboagent.backends.spatial import SpatialLMBackend

memory = CompositeMemory(
    memories={
        "episodic": TieredMemory(),
        "spatial": SpatialMemory(
            frame_key="spatial_frames",
            map_frame="map",
            voxel_size_m=0.03,
            pixel_stride=8,
            keyframe_translation_m=0.05,
            keyframe_rotation_deg=5.0,
            artifact_dir="artifacts/spatial",
            session_export_interval_keyframes=10,
            spatial_backend=SpatialLMBackend(model_path="<MODEL_PATH>"),
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
  class_path: omniroboagent.agent_core.memories.composite.CompositeMemory
  init_args:
    memories:
      episodic:
        class_path: omniroboagent.agent_core.memories.TieredMemory
      spatial:
        class_path: omniroboagent.agent_core.memories.spatial.SpatialMemory
        init_args:
          frame_key: spatial_frames
          map_frame: map
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
`LanguageSkillPlanner._memory_prompt()` 检测到该字段后会将完整 `spatial` 内容序列化
到 `Memory context`；即使其值是空字典，也会保留该字段。

## 方式一：SLAM 实时构图

### Observation 接入契约

未配置 `global_scene_ply` 时，`SpatialMemory.update()` 从 observation 中读取
`frame_key`。默认 `frame_key="spatial_frames"`，所以 Environment 或上游 integration
必须让最新 observation 带有 `spatial_frames`：

```python
state = {
    "observation": {
        "spatial_frames": [spatial_frame],
    }
}
memory.update(state, event={})
```

`observation["spatial_frames"]` 可以直接是一份 frame mapping，也可以是 frame
mapping 的 list/tuple。字段不存在时本次 `update()` 是 no-op；字段存在但不是 frame
或 frame 序列时抛出 `TypeError`。如需使用其他字段名，可在构造或配置中修改
`frame_key`，但 observation 的 key 必须与其完全一致。

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

当 `event["environment_result"]` 是 mapping 时，`update()` 优先读取其中的
`observation`；否则读取 `state["observation"]`。典型闭环应由 Environment 在
`reset()` 返回的初始 observation，以及每次 `execute()` 返回的新 observation 中持续
提供 `spatial_frames`。也可以绕过 observation，直接调用
`memory.ingest(spatial_frame)`。

### 用户真正需要提供的数据

在线构图真正依赖且必须准确提供的只有四类数据：

- 与深度对齐的 `rgb`；
- 单位为米的 `depth_m`；
- 对应的相机 `intrinsics`；
- 单位为米的绝对相机位姿 `T_world_camera`。

`timestamp_ns`、`camera_id`、`frame_id` 和 `world_frame` 仍需作为 key 放进 frame，
但不要求额外接入真实机器人 metadata 系统。单相机场景可以直接使用下面的简单值：

| 字段 | 简单用法 | 注意事项 |
| --- | --- | --- |
| `timestamp_ns` | `time.time_ns()`，或从 `0` 开始递增的整数 | 只用于轨迹、最近更新时间和 voxel metadata；不要求与外部时钟同步。随机非负整数也能通过校验，但不利于排查帧顺序，不推荐 |
| `camera_id` | 固定写 `"camera"` | 必须在同一相机的连续帧间保持不变；关键帧筛选按该字段保存上一位姿，不能每帧随机生成 |
| `frame_id` | 固定写 `"camera"` 或 `"camera_optical_frame"` | 当前只用于轨迹和诊断记录，不参与几何计算或关键帧判断 |
| `world_frame` | 固定写 `"map"` | `map_frame` 默认就是 `"map"`；只有显式修改 `SpatialMemory.map_frame` 时才需要同步修改 |

完整 frame 仍是一个 mapping，字段如下：

| 字段 | 类型 / shape | 单位与约束 |
| --- | --- | --- |
| `timestamp_ns` | 非负整数 | 可直接使用 `time.time_ns()` 或递增计数，不要求真实传感器时间 |
| `camera_id` | 非空字符串 | 单相机固定为 `camera` 即可；多相机分别使用稳定且不同的名称 |
| `frame_id` | 非空字符串 | 可固定为 `camera`；仅用于记录 |
| `world_frame` | 非空字符串 | 保持默认值 `map` 即可；必须与 `SpatialMemory.map_frame` 相同 |
| `rgb` | `H x W x 3` array-like | 与深度逐像素对齐的 RGB，数值应为 `0..255` |
| `depth_m` | `H x W` array-like | 与 RGB 对齐的深度，单位必须是 m |
| `intrinsics` | mapping | 必须包含 `width`、`height`、`fx`、`fy`、`cx`、`cy`；焦距和主点单位为 pixel |
| `T_world_camera` | `4 x 4` 数值矩阵 | 绝对 camera-to-map 刚体变换；平移分量单位必须是 m |

单相机的最小完整结构如下：

```python
from time import time_ns

spatial_frame = {
    "timestamp_ns": time_ns(),
    "camera_id": "camera",
    "frame_id": "camera",
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

### 单位、坐标系与校验

- RGB 与深度必须在上游完成时间同步、像素对齐和去畸变；Memory 不做 registration。
- 反投影使用 pinhole 模型。相机光学坐标为 `+X` 向右、`+Y` 向下、`+Z` 向前：
  `x=(u-cx)*depth/fx`、`y=(v-cy)*depth/fy`、`z=depth`。
- `depth_m` 的每个有效值都必须是米。NaN、Inf，以及超出 `depth_min_m` 到
  `depth_max_m` 范围的值会被忽略；默认有效范围是 `0.2..5.0 m`。
- RGB、深度的宽高必须与 `intrinsics.width/height` 完全一致；`width/height` 必须是
  正整数，`fx/fy` 必须是正有限数，`cx/cy` 必须是有限数。
- `T_world_camera` 是绝对位姿，不是相邻帧增量，满足
  `point_world = T_world_camera @ [x, y, z, 1]`。旋转部分必须是有限、正交且
  determinant 为 `1` 的旋转矩阵；最后一行必须是 `[0, 0, 0, 1]`；平移分量使用米。
- `world_frame` 必须等于配置的 `map_frame`。所有相机的位姿必须落在同一个
  `map_frame` 中，并使用同一米制尺度。
- 当前实现会在送入 SpatialLM 和导出 PLY 前把在线 map 点固定转换为
  `(x, y, z) -> (x, z, -y)`，得到 `+X` 向右、`+Y` 向前、`+Z` 向上的坐标。因此上游
  SLAM/map 坐标必须与该源轴约定兼容；如果上游已经输出 Z-up 点云，应先转换到该
  在线输入约定，或改用下面的全局 Z-up PLY 方式。
- 位姿估计、回环检测、相机与机器人基座的外参链计算不属于 Memory，应由上游
  integration 提供。

### 关键帧与地图更新

在线建图模式的数据处理流程为：

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
XYZRGB(A)。`.ply` 路径直接交给 `SpatialLMBackend.infer_ply()`，由 SpatialLM 的
`load_o3d_pcd()` 和 `get_points_and_colors()` 读取为 NumPy points/colors，不做坐标
旋转；因此外部 PLY 必须已经是 Z-up。mapping/数组输入则在
`_localize_with_spatiallm()` 内按
`(x, y, z) -> (x, z, -y)` 转为 `+X` 向右、`+Y` 向前、`+Z` 向上，且不会修改原
输入。两条路径最终都调用 `SpatialLMBackend.infer_points()`；普通帧不会触发
SpatialLM。

`SpatialLMBackend` 在 Memory lifecycle 内长期复用，由 `SpatialMemory.close()` 释放。
未配置 backend 时建图、轨迹和 artifact 导出继续工作，但显式 `update_layout()` 会
抛出错误。PLY 支持范围与当前 SpatialLM/Open3D 环境一致。

## 方式二：全局场景 PLY

已经由 SLAM、扫描或离线重建得到完整场景点云时，可以跳过在线 RGB-D 融合，直接
配置 `global_scene_ply`：

```yaml
memory:
  class_path: omniroboagent.agent_core.memories.spatial.SpatialMemory
  init_args:
    global_scene_ply: <GLOBAL_SCENE_PLY>
    spatial_backend:
      class_path: omniroboagent.backends.spatial.SpatialLMBackend
      init_args:
        model_path: <MODEL_PATH>
    spatial_detect_type: all
    spatial_seed: 42
```

全局 PLY 的用户输入契约：

- 所有 `x/y/z` 坐标和尺寸必须以米为单位；代码不会从 PLY metadata 推断或自动换算
  mm、cm 等其他尺度。
- 必须是右手系 Z-up：`X/Y` 构成水平面，`+Z` 竖直向上；墙体最好已经与水平
  `X/Y` 轴对齐。全局 PLY 不会再执行在线模式的 `(x, y, z) -> (x, z, -y)` 转换。
- 文件必须是非空 `.ply`，并能被 SpatialLM 的 `load_o3d_pcd()` / Open3D 读取为有限
  XYZ points。
- 颜色由 SpatialLM 的 `get_points_and_colors()` 处理；没有颜色时使用全零 RGB，
  `0..1` 范围的颜色会转为 `0..255`。
- `global_scene_ply` 必须与 `spatial_backend` 同时配置。

构造 `SpatialMemory` 时会立即读取 PLY 并只调用一次 `SpatialLMBackend`。定位结果在
`reset()` 后继续保留；后续 `update()`、`ingest()` 和 `update_layout()` 直接复用
缓存，不读取 `observation["spatial_frames"]`，不更新 voxel map、不记录轨迹，也不
触发自动 checkpoint。此模式下 `point_cloud()` 和 `trajectory()` 为空，原始 PLY 是
场景点云的权威来源。

`export_ply()` / `export_session()` 不用于全局 PLY 模式；`recall()` 始终返回构造时
生成的完整定位。

### EB-ALFRED 全局场景 smoke 配置

仓库提供了可参考的 [RunConfig](../../configs/runs/eb_alfred_spatial_memory_smoke.yaml)
和配套的 [AgentConfig](../../configs/agents/eb_alfred_spatial_memory.yaml)。在仓库根目录、
完成 [SpatialMemory backend 环境安装](spatialmemory_backend.md) 后，可以运行：

```bash
bash scripts/run_eb_alfred_xvfb.sh configs/runs/eb_alfred_spatial_memory_smoke.yaml
```

这个示例通过 AgentConfig 中的 `global_scene_ply` 启用全局场景点云模式：启动时读取
`SpatialLM/examples/spatiallm_demo/input/scene0000_00.ply` 并执行一次空间定位，之后将
缓存的 `memory_context["spatial"]` 提供给 Planner。它不会从 EB-ALFRED observation
读取 `spatial_frames`，也不会进行 SLAM 实时构图。

这里的 `scene0000_00.ply` 是 [SpatialLM demo](../../SpatialLM/examples/spatiallm_demo/README.md)
附带的测试场景，并不是当前 EB-ALFRED episode 的真实场景点云。因此，该配置仅用于
检查全局 PLY 加载、SpatialLM 推理、`CompositeMemory` 合并和 Planner 空间上下文注入
这条集成链路，不能用于评估空间记忆对该 episode 的真实规划效果。接入真实任务时，
必须将 `global_scene_ply` 替换为与当前任务环境对应的米制、右手系、Z-up 全局场景点云。

配套 AgentConfig 中的 `global_scene_ply`、`model_path` 和 LLM `base_url` 是维护者机器与
服务环境的示例值，不是框架默认值；运行前需要替换为本机仓库路径、实际 checkpoint
路径和可用的模型服务地址。运行输出写入
`runs/eb_alfred_spatial_memory_smoke/`。

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
| `global_scene_ply` | `None` | 完整全局场景 PLY；配置后初始化时只定位一次并禁用在线建图 |

## 当前边界

- 当前重建表示为增量 voxel 点云，不包含 TSDF、网格生成或表面补洞。
- 当前不包含回环检测、位姿图优化和历史地图重融合；外参误差会累积到地图中。
- 当前不进行动态物体过滤、多相机同步或 RGB-depth registration。
- 在线建图模式下 SpatialLM 在每个成功融合关键帧后同步运行，尚未实现异步推理、
  队列或频率控制；全局 PLY 模式只在构造时运行一次。
- 真实 checkpoint 的 GPU 显存、延迟和长 session 稳定性尚未完成 smoke 验证。
- 在线 RGB-D 反投影使用不依赖 NumPy/Open3D 的通用实现；高分辨率实时场景可在
  保持输入与 `recall()` 契约不变的情况下替换为 NumPy、Open3D 或 CUDA 后端。
  PLY 文件读取则直接复用 SpatialLM 的 Open3D helper。
