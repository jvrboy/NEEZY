"""Read-only microkernel status and opt-in local benchmark commands."""

from __future__ import annotations

from ..kernel_benchmark import benchmark_kernels
from ..microkernels import kernel_status
from .common import _emit, _table


def cmd_kernels(args, fetch, out) -> int:
    del fetch
    if args.action == "status":
        document = kernel_status()
        if args.json:
            _emit(out, document)
        else:
            out.write(f"Backend: {document['backend']}\n")
            out.write("Kernels: " + ", ".join(document["kernels"]) + "\n")
            out.write("Deterministic: yes\nNative dependency: none\n")
        return 0
    if args.action == "benchmark":
        document = benchmark_kernels(iterations=args.iterations, size=args.candles)
        if args.json:
            _emit(out, document)
            return 0
        rows = []
        for name, values in document["kernels"].items():
            speedup = values["speedup"]
            rows.append(
                (
                    name,
                    f"{values['optimized_ms']:.3f}",
                    f"{values['reference_ms']:.3f}",
                    f"{speedup:.2f}x" if speedup is not None else "n/a",
                )
            )
        out.write(
            f"Correctness-checked local benchmark: {args.iterations} iterations, "
            f"{args.candles} candles\n"
        )
        _table(out, ["KERNEL", "OPTIMIZED MS", "REFERENCE MS", "RATIO"], rows)
        out.write("Timings are local measurements, not a guarantee on other devices.\n")
        return 0
    raise ValueError(f"unknown kernels action {args.action!r}")
