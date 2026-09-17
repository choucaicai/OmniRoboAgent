#!/usr/bin/env python3
"""Train LeRobot PI0.5 on the local streaming LIBERO subtask dataset.

LeRobot 0.5's streaming loader leaves embedded image columns as PIL images,
whereas its regular loader converts them to float CHW tensors. Apply that same
conversion here before entering the unmodified LeRobot training loop.
"""

from __future__ import annotations

import os

import accelerate
import numpy as np
import torch
from accelerate import DataLoaderConfiguration
from lerobot.datasets import io_utils, streaming_dataset
from PIL import Image as PILImage
from torchvision.transforms.functional import pil_to_tensor

TOKENIZER_DIR = os.environ.get("PALIGEMMA_TOKENIZER")
RAW_TO_POLICY = {
    "image": "observation.images.image",
    "wrist_image": "observation.images.image2",
    "state": "observation.state",
    "actions": "action",
}


def streaming_item_to_torch(item: dict) -> dict:
    item = {RAW_TO_POLICY.get(key, key): value for key, value in item.items()}
    for key, value in item.items():
        if isinstance(value, PILImage.Image):
            item[key] = pil_to_tensor(value).float().div_(255.0)
        elif isinstance(value, (np.ndarray, list)) and key != "task":
            item[key] = torch.as_tensor(value)
    return item


io_utils.item_to_torch = streaming_item_to_torch
streaming_dataset.item_to_torch = streaming_item_to_torch

# Accelerate defaults to dispatching an IterableDataset from rank 0.  That path
# concatenates every batch field before scattering it and therefore crashes on
# LeRobot's natural-language ``task`` strings.  Let each DDP rank consume its
# own streaming iterator instead; tensor gradients are still synchronized by
# DDP in the usual way.
_Accelerator = accelerate.Accelerator


def accelerator_without_batch_dispatch(*args, **kwargs):
    kwargs.setdefault(
        "dataloader_config",
        DataLoaderConfiguration(dispatch_batches=False, split_batches=False),
    )
    return _Accelerator(*args, **kwargs)


accelerate.Accelerator = accelerator_without_batch_dispatch

import lerobot.scripts.lerobot_train as train_module  # noqa: E402

_make_pre_post_processors = train_module.make_pre_post_processors


def make_pre_post_processors_with_local_tokenizer(*args, **kwargs):
    if not TOKENIZER_DIR:
        raise RuntimeError("Set PALIGEMMA_TOKENIZER to a local tokenizer directory")
    overrides = dict(kwargs.get("preprocessor_overrides", {}))
    tokenizer_overrides = dict(overrides.get("tokenizer_processor", {}))
    tokenizer_overrides["tokenizer_name"] = TOKENIZER_DIR
    overrides["tokenizer_processor"] = tokenizer_overrides
    kwargs["preprocessor_overrides"] = overrides
    return _make_pre_post_processors(*args, **kwargs)


train_module.make_pre_post_processors = make_pre_post_processors_with_local_tokenizer


if __name__ == "__main__":
    train_module.main()
