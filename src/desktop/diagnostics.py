"""Read-only diagnostics for the V8 desktop workbench.

Connection diagnostics inspect the local Windows adapter state and perform one
bounded HELLO probe. They never restart services or change network settings.
FPGA resource figures are displayed only when explicitly bound to the selected
target device and are labelled as static build data, not live board telemetry.
"""

from __future__ import annotations

import copy
import errno
import hashlib
import json
import math
import os
import re
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from .protocol import BoardProtocolError, PROTOCOL
except ImportError:  # Allows running this module directly from the deployment folder.
    from protocol import BoardProtocolError, PROTOCOL


_PROBE_TIMEOUT_SECONDS = 8.0
_LOCAL_QUERY_TIMEOUT_SECONDS = 8.0
_RESOURCE_ROWS = (
    ("Slice LUTs", "LUT", "LUT"),
    ("Slice Registers", "寄存器（FF）", "FF"),
    ("Block RAM Tile", "Block RAM Tile", "BRAM"),
    ("DSPs", "DSP", "DSP"),
)


def _stage(name: str, status: str, detail: str, action: str = "") -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail, "action": action}


def _query_local_network() -> dict[str, Any]:
    """Return local IPv4 adapter facts on Windows; never mutate adapter state."""
    if sys.platform != "win32":
        return {"adapters": [], "addresses": [], "error": "Windows adapter inspection is unavailable on this platform"}

    script = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$adapters = @(Get-NetAdapter -ErrorAction SilentlyContinue | ForEach-Object {
  [pscustomobject]@{ name=[string]$_.Name; status=[string]$_.Status; ifIndex=[int]$_.ifIndex }
})
$addresses = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | ForEach-Object {
  [pscustomobject]@{ ifIndex=[int]$_.InterfaceIndex; address=[string]$_.IPAddress; state=[string]$_.AddressState }
})
[pscustomobject]@{ adapters=$adapters; addresses=$addresses } | ConvertTo-Json -Compress -Depth 4
"""
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=_LOCAL_QUERY_TIMEOUT_SECONDS,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired:
        return {"adapters": [], "addresses": [], "error": "读取本机网卡信息超时"}
    except OSError as exc:
        return {"adapters": [], "addresses": [], "error": f"local adapter query unavailable: {exc}"}
    except UnicodeError as exc:
        return {"adapters": [], "addresses": [], "error": f"adapter query output could not be decoded: {exc}"}
    if result.returncode != 0:
        reason = (result.stderr or "").strip() or f"PowerShell exited with code {result.returncode}"
        return {"adapters": [], "addresses": [], "error": reason[:240]}
    if not result.stdout:
        return {"adapters": [], "addresses": [], "error": "adapter query returned empty output"}
    try:
        payload = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        return {"adapters": [], "addresses": [], "error": f"adapter query returned invalid JSON: {exc}"}
    if not isinstance(payload, dict):
        return {"adapters": [], "addresses": [], "error": "adapter query returned an unexpected value"}
    payload.setdefault("adapters", [])
    payload.setdefault("addresses", [])
    payload["adapters"] = payload["adapters"] if isinstance(payload["adapters"], list) else [payload["adapters"]]
    payload["addresses"] = payload["addresses"] if isinstance(payload["addresses"], list) else [payload["addresses"]]
    return payload


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _local_network_stages(client: Any, facts: dict[str, Any]) -> list[dict[str, str]]:
    adapters = [a for a in facts.get("adapters", []) if isinstance(a, dict)]
    addresses = [a for a in facts.get("addresses", []) if isinstance(a, dict)]
    query_error = facts.get("error")
    requested_index = _int_or_none(getattr(client, "interface_index", None))
    requested_ip = getattr(client, "local_address", None)

    if query_error:
        return [_stage(
            "本机网卡与 IPv4",
            "warn",
            f"无法读取 Windows 网卡状态（{query_error}）；会继续尝试配置的网络探测。",
            "可在 Windows 网络设置中检查网卡状态和 IPv4 地址。",
        )]

    stages: list[dict[str, str]] = []
    selected_adapter: dict[str, Any] | None = None
    if requested_index is not None:
        selected_adapter = next((a for a in adapters if _int_or_none(a.get("ifIndex")) == requested_index), None)
        if selected_adapter is None:
            stages.append(_stage(
                "本机网卡",
                "fail",
                f"设置指定的网卡接口编号 {requested_index} 在本机网卡列表中不存在。",
                "检查高级设置中的网卡编号，或重新选择当前连接的以太网网卡。",
            ))
        else:
            name = str(selected_adapter.get("name") or f"接口 {requested_index}")
            status = str(selected_adapter.get("status") or "Unknown")
            if status.casefold() == "up":
                stages.append(_stage("本机网卡", "pass", f"{name}（接口 {requested_index}）状态为 Up。"))
            else:
                stages.append(_stage(
                    "本机网卡",
                    "fail",
                    f"{name}（接口 {requested_index}）当前状态为 {status}，本机网络接口未处于 Up 状态。",
                    "检查网线和网口连接，并在 Windows 中启用该网卡。",
                ))
    elif adapters:
        up_adapters = [a for a in adapters if str(a.get("status", "")).casefold() == "up"]
        if up_adapters:
            selected_adapter = up_adapters[0]
            stages.append(_stage("本机网卡", "pass", f"检测到已启用网卡 {selected_adapter.get('name', '未知')}。"))
        else:
            stages.append(_stage(
                "本机网卡",
                "fail",
                "Windows 当前没有状态为 Up 的网络适配器。",
                "检查网线、交换机端口，并在 Windows 中启用用于连接开发板的网卡。",
            ))
    else:
        stages.append(_stage(
            "本机网卡",
            "warn",
            "系统没有返回网卡记录，无法判断本机网卡是否已连接。",
            "检查 Windows 网络设置中的以太网网卡状态。",
        ))

    selected_index = requested_index
    if selected_index is None and selected_adapter is not None:
        selected_index = _int_or_none(selected_adapter.get("ifIndex"))

    if requested_ip:
        matching_ip = next((
            a for a in addresses
            if str(a.get("address", "")).strip() == str(requested_ip)
            and (selected_index is None or _int_or_none(a.get("ifIndex")) == selected_index)
        ), None)
        if matching_ip is None:
            stages.append(_stage(
                "本机 IPv4 地址",
                "fail",
                f"配置的本机 IPv4 地址 {requested_ip} 未配置在所选网卡上。",
                "核对工作台高级设置中的本机 IP 与 Windows 网卡 IPv4 配置。",
            ))
        elif str(matching_ip.get("state", "Preferred")).casefold() == "duplicate":
            stages.append(_stage(
                "本机 IPv4 地址",
                "fail",
                f"本机地址 {requested_ip} 被 Windows 标记为重复地址。",
                "检查局域网地址冲突，并为本机网卡配置唯一 IP。",
            ))
        else:
            stages.append(_stage("本机 IPv4 地址", "pass", f"配置的本机地址 {requested_ip} 存在。"))
    elif selected_index is not None:
        usable = [a for a in addresses if _int_or_none(a.get("ifIndex")) == selected_index]
        if usable:
            formatted = ", ".join(str(a.get("address", "")) for a in usable if a.get("address"))
            stages.append(_stage("本机 IPv4 地址", "pass", f"接口 {selected_index} 已配置 IPv4：{formatted or '已检测到'}。"))
        else:
            stages.append(_stage(
                "本机 IPv4 地址",
                "fail",
                f"指定网卡接口 {selected_index} 没有检测到 IPv4 地址。",
                "为该网卡配置正确的本机 IPv4 地址，并与开发板处于可路由的网段。",
            ))
    else:
        up_indices = {
            _int_or_none(a.get("ifIndex")) for a in adapters
            if str(a.get("status", "")).casefold() == "up"
        }
        ipv4 = [a for a in addresses if _int_or_none(a.get("ifIndex")) in up_indices]
        if ipv4:
            stages.append(_stage("本机 IPv4 地址", "pass", "已启用网卡上检测到 IPv4 地址。"))
        else:
            stages.append(_stage(
                "本机 IPv4 地址",
                "warn",
                "已启用网卡上没有检测到 IPv4 地址，无法从本机配置确认目标网络。",
                "检查网卡 IPv4 配置；若使用自动获取地址，请确认 DHCP 已完成。",
            ))
    return stages


def _exception_chain(exc: BaseException):
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _failed_probe_stage(exc: BaseException, client: Any) -> dict[str, str]:
    chain = list(_exception_chain(exc))
    os_errors = [item for item in chain if isinstance(item, OSError)]
    text = " | ".join(str(item) for item in chain).strip()
    lower = text.casefold()
    host = getattr(client, "host", "开发板")
    port = getattr(client, "port", "?")

    if any(isinstance(item, socket.gaierror) for item in os_errors):
        return _stage(
            "目标地址解析",
            "fail",
            f"无法解析目标地址 {host!s}；这属于地址/名称配置问题。详情：{text[:240]}",
            "核对工作台设置中的开发板 IPv4 地址或主机名。",
        )
    if any(isinstance(item, (socket.timeout, TimeoutError)) for item in chain) or any(
        getattr(item, "errno", None) == errno.ETIMEDOUT for item in os_errors
    ):
        return _stage(
            "开发板网络连接",
            "fail",
            f"连接 {host}:{port} 超时。可能是开发板未上电或尚未启动，也可能是网线、交换机、本机 IP、目标 IP 或网络路径有问题；仅凭超时无法判断板卡是否已上电。",
            "确认板卡供电并等待系统启动，检查网线和本机/开发板 IP；再确认板端 V8 服务已启动且端口正确。",
        )
    if any(isinstance(item, ConnectionRefusedError) for item in os_errors) or any(
        getattr(item, "errno", None) == errno.ECONNREFUSED for item in os_errors
    ):
        return _stage(
            "开发板服务端口",
            "fail",
            f"目标 {host}:{port} 拒绝了 TCP 连接，说明该端口当前没有接受 V8 工作台连接的服务，或端口配置不正确。",
            "确认开发板已启动并运行 V8 服务，核对服务监听端口及工作台端口设置。",
        )
    if any(getattr(item, "errno", None) in (errno.ENETUNREACH, errno.EHOSTUNREACH) for item in os_errors):
        return _stage(
            "本机到开发板的网络路径",
            "fail",
            f"操作系统报告到 {host} 的网络或主机不可达；当前路由/链路无法到达目标。详情：{text[:200]}",
            "检查所选网卡、网线、目标 IP 与本机 IP/掩码配置。",
        )
    if any(getattr(item, "errno", None) == errno.EADDRNOTAVAIL for item in os_errors):
        return _stage(
            "本机绑定地址",
            "fail",
            f"工作台无法使用配置的本机地址或网卡发起连接。详情：{text[:200]}",
            "确认高级设置里的本机 IP/网卡编号与 Windows 当前配置一致。",
        )
    if any(getattr(item, "errno", None) == errno.ECONNRESET for item in os_errors):
        return _stage(
            "开发板 HELLO 响应",
            "fail",
            f"目标已接受连接，但在完成 V8 HELLO 握手前重置了连接。详情：{text[:200]}",
            "确认板端服务已完全启动，并检查端口是否由 V8 服务监听。",
        )
    if any(isinstance(item, BoardProtocolError) for item in chain) or any(
        phrase in lower for phrase in ("invalid json", "json frame", "connection closed before complete response", "hello")
    ):
        return _stage(
            "开发板 HELLO 响应",
            "fail",
            f"TCP 端点没有返回完整、有效的 HELLO JSON 响应，可能连接到了错误服务或板端服务未完整启动。详情：{text[:220]}",
            "确认目标端口运行的是 V8 板端服务，并等待启动完成后重试。",
        )
    return _stage(
        "开发板连接探测",
        "fail",
        f"连接探测失败：{text[:260] or type(exc).__name__}。",
        "按上方本机网卡/IP状态检查网络，再核对开发板地址和服务端口。",
    )


def _identity_stages(client: Any, hello: Any, local: Any, peer: Any) -> list[dict[str, str]]:
    if not isinstance(hello, dict):
        return [
            _stage("V8 协议版本", "fail", "HELLO 回复不是 JSON 对象。", "确认端口运行的是 V8 板端服务。"),
            _stage("模型与类别身份", "skipped", "未收到可核验的 HELLO 字段。"),
            _stage("板端运行位置", "skipped", "未收到可核验的运行位置字段。"),
        ]

    stages = [_stage(
        "TCP / HELLO",
        "pass",
        f"已与 {peer[0]}:{peer[1]} 完成 HELLO（本机端点 {local[0]}:{local[1]}）。",
    )]
    received_protocol = hello.get("protocol")
    if hello.get("type") != "HELLO_OK" or received_protocol != PROTOCOL:
        received = str(received_protocol or hello.get("type") or "缺失")
        looks_v3 = "v3" in received.casefold() or "yolov3" in received.casefold()
        if looks_v3:
            detail = f"目标端点返回旧版/非 V8 协议标识 {received!r}，不能与当前 V8 工作台握手。"
        else:
            detail = f"目标端点返回的 HELLO 类型或协议版本不匹配（收到 {received!r}，要求 {PROTOCOL!r}）。"
        stages.extend([
            _stage("V8 协议版本", "fail", detail, "切换到与 MODEL.V8P 配套的 V8 板端程序和端口。"),
            _stage("模型与类别身份", "skipped", "协议版本不匹配，未继续核对模型和类别。"),
            _stage("推理输入语义", "skipped", "协议版本不匹配，未继续核对输入语义。"),
            _stage("板端运行位置", "skipped", "协议版本不匹配，未继续核对运行位置。"),
        ])
        return stages

    stages.append(_stage("V8 协议版本", "pass", f"协议版本为 {PROTOCOL}。"))
    mismatches: list[str] = []
    expected_model = getattr(client, "model_sha256", None)
    expected_classes = getattr(client, "classes_sha256", None)
    expected_count = getattr(client, "class_count", None)
    expected_domain = getattr(client, "class_domain", None)
    if hello.get("model_sha256") != expected_model:
        mismatches.append("模型包 SHA-256 不一致")
    if hello.get("classes_sha256") != expected_classes:
        mismatches.append("类别名称与顺序 SHA-256 不一致")
    advertised_count = hello.get("class_count")
    advertised_domain = hello.get("class_domain")
    if expected_count == 9 or advertised_count is not None or advertised_domain is not None:
        if (type(advertised_count) is not int or advertised_count != expected_count
                or advertised_domain != expected_domain):
            mismatches.append("类别数或模型域不一致")
    if mismatches:
        stages.append(_stage(
            "模型与类别身份",
            "fail",
            "板端与本机不匹配：" + "、".join(mismatches) + "。",
            "将与板端固件配套的 MODEL.V8P 和类别表配置到工作台。",
        ))
    else:
        stages.append(_stage("模型与类别身份", "pass",
                             f"板端模型包及 {expected_count} 类 {expected_domain} 映射与本机配置一致。"))

    semantic_mismatches = []
    if hello.get("input") != "rgb-u8-640-letterbox114":
        semantic_mismatches.append("输入格式")
    if hello.get("box_space") != "normalized-model-xyxy":
        semantic_mismatches.append("检测框坐标格式")
    if semantic_mismatches:
        stages.append(_stage(
            "推理输入语义",
            "fail",
            "板端与工作台的" + "、".join(semantic_mismatches) + "不一致。",
            "使用同一版本的板端程序和 V8 工作台配置。",
        ))
    else:
        stages.append(_stage("推理输入语义", "pass", "RGB 输入尺寸/填充及检测框坐标格式一致。"))

    runtime = hello.get("runtime")
    if runtime == "board":
        stages.append(_stage("板端运行位置", "pass", "服务声明运行位置为开发板。"))
    elif runtime == "host_reference" and bool(getattr(client, "allow_host_reference", False)):
        stages.append(_stage(
            "板端运行位置",
            "warn",
            "当前连接的是电脑上的参考服务，不能作为 FPGA 开发板运行证据。",
            "若要检查实板，请关闭主机参考模式并连接开发板端点。",
        ))
    else:
        stages.append(_stage(
            "板端运行位置",
            "fail",
            f"服务运行位置字段为 {runtime!r}，无法确认推理在开发板上执行。",
            "确认连接到开发板 V8 服务，不要把电脑参考服务作为板端结果。",
        ))
    return stages


def diagnose_connection(client: Any) -> dict[str, Any]:
    """Inspect local network state and perform one HELLO-only probe (max 8 s).

    The client is shallow-copied to cap its timeout, so its configured timeout
    and all other state remain unchanged. No inference request is sent.
    """
    stages = _local_network_stages(client, _query_local_network())
    try:
        probe_client = copy.copy(client)
        configured_timeout = float(getattr(client, "timeout", _PROBE_TIMEOUT_SECONDS))
        probe_client.timeout = min(max(configured_timeout, 0.1), _PROBE_TIMEOUT_SECONDS)
        hello, local, peer = probe_client.probe_identity()
        stages.extend(_identity_stages(client, hello, local, peer))
    except Exception as exc:  # Diagnostic UI must report the failing stage instead of crashing.
        stages.append(_failed_probe_stage(exc, client))
        stages.extend([
            _stage("V8 协议版本", "skipped", "HELLO 探测未完成，无法核对协议版本。"),
            _stage("模型与类别身份", "skipped", "HELLO 探测未完成，无法核对模型与类别。"),
            _stage("板端运行位置", "skipped", "HELLO 探测未完成，无法核对运行位置。"),
        ])

    failures = [item for item in stages if item["status"] == "fail"]
    warnings = [item for item in stages if item["status"] == "warn"]
    ok = not failures
    if failures:
        message = failures[0]["detail"]
    elif any(item["name"] == "板端运行位置" for item in warnings):
        message = next(item["detail"] for item in warnings if item["name"] == "板端运行位置")
    elif warnings:
        message = "连接检查通过：开发板 V8 服务、模型和类别身份均匹配。本机网络信息有提示，详见“诊断详情”。"
    else:
        message = "连接检查通过：开发板 V8 服务、模型和类别身份均匹配。"
    return {"ok": ok, "message": message, "stages": stages}


def _number(value: str) -> int | float:
    parsed = float(value.replace(",", "").strip())
    if not math.isfinite(parsed):
        raise ValueError("resource report contains a non-finite number")
    return int(parsed) if parsed.is_integer() else parsed


def _resource_metric(report: str, row_name: str, display_name: str) -> dict[str, int | float]:
    columns = None
    for line in report.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(name in cells for name in ("Used", "Available", "Util%")):
            columns = tuple(cells.index(name) for name in ("Used", "Available", "Util%"))
            continue
        if len(cells) < 5 or cells[0] != row_name:
            continue
        if columns is None or max(columns) >= len(cells):
            raise ValueError(f"resource table header missing: {row_name}")
        used, available, percent = (_number(cells[index]) for index in columns)
        if available <= 0 or used < 0 or used > available or not 0 <= percent <= 100:
            raise ValueError(f"invalid resource values for {row_name}")
        if abs(percent - used / available * 100) > 0.011:
            raise ValueError(f"resource percentage does not match counts: {row_name}")
        return {"name": display_name, "used": used, "total": available, "percent": percent}
    raise ValueError(f"resource row not found: {row_name}")


def load_fpga_resources(*, target_device: str | None = None,
                        report_path: str | Path | None = None,
                        expected_sha256: str | None = None) -> dict[str, Any]:
    """Load a routed report only when its target device is explicitly selected."""
    result: dict[str, Any] = {
        "title": "FPGA 资源占用（未评估）",
        "note": "尚未选定 Zynq-7Z100 目标器件，资源占用未评估。旧 Zynq-7020 报告仅代表旧基线，不代表新目标。",
        "metrics": [],
        "source": str(report_path) if report_path is not None else None,
        "device": target_device,
        "available": False,
    }
    if not target_device:
        return result
    if not report_path:
        result["note"] = f"目标器件为 {target_device}，但未提供对应的 Vivado 布线后资源报告。"
        return result
    try:
        blob = Path(report_path).read_bytes()
        if expected_sha256 is not None and hashlib.sha256(blob).hexdigest() != expected_sha256:
            raise ValueError("resource report SHA-256 does not match the configured build")
        report = blob.decode("utf-8", errors="replace")
        state = re.search(r"^\|\s*Design State\s*:\s*([^|\r\n]+)", report, re.MULTILINE)
        if not state or state.group(1).strip() not in ("Routed", "Physopt postRoute"):
            raise ValueError("report is not a post-route implementation report")
        device_match = re.search(r"^\|\s*Device\s*:\s*([^|\r\n]+)", report, re.MULTILINE)
        if not device_match or device_match.group(1).strip().casefold() != target_device.strip().casefold():
            raise ValueError("report device does not match the selected target device")
        metrics = [
            _resource_metric(report, row_name, display_name)
            for row_name, display_name, _ in _RESOURCE_ROWS
        ]
    except (OSError, ValueError) as exc:
        result["note"] = f"无法读取与目标器件 {target_device} 匹配的布线后资源报告：{exc}。没有显示可用量。"
        return result
    result["metrics"] = metrics
    result["available"] = True
    result["note"] = (
        f"目标器件 {target_device} 的 Vivado 布线后静态用量，不是板上实时数据；"
        "当前服务没有提供 CPU、DDR、温度或运行中 bitstream 身份遥测。"
    )
    return result

