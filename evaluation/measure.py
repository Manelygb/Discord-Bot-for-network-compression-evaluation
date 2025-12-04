# evaluation/measure.py
import pathlib
import json
import time

def measure_model(file_path: str, out_path: str = None) -> dict:
    """
    Example placeholder:
      - file size (bytes)
      - parameter_count (if loadable)
      - flops (if calculable)
      - inference_time (run N inferences on dummy input)
    Replace with actual model loaders (torch, onnxruntime, tflite) and measurement utils.
    """
    p = pathlib.Path(file_path)
    if not p.exists():
        raise FileNotFoundError(file_path)

    result = {
        "file_size_bytes": p.stat().st_size,
        "parameter_count": None,   # fill by loading model
        "flops": None,             # use ptflops or other lib
        "inference_time_ms": None,
    }

    # Example: if it's a torch model you can load it and count params
    # import torch
    # model = torch.load(str(p), map_location="cpu")
    # param_count = sum(p.numel() for p in model.parameters())
    # result["parameter_count"] = param_count

    # Also compute dummy inference times as an approximation
    # --- omitted here ---

    return result
