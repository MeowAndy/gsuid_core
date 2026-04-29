import os
import time
import platform
import subprocess
from typing import Optional
from pathlib import Path

from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.server import core_shutdown_execute
from gsuid_core.subscribe import gs_subscribe
from gsuid_core.utils.database.models import Subscribe
from gsuid_core.utils.plugins_update.utils import check_start_tool
from gsuid_core.utils.plugins_config.gs_config import core_plugins_config

bot_start = Path(__file__).parents[3] / "core.py"
restart_sh_path = Path().cwd() / "gs_restart.sh"
update_log_path = Path(__file__).parent / "update_log.json"

_restart_sh = """#!/bin/bash
kill -9 {}
{} &"""


def get_restart_command():
    is_use_custom_restart_command = core_plugins_config.get_config("is_use_custom_restart_command").data
    if is_use_custom_restart_command:
        restart_command = core_plugins_config.get_config("restart_command").data
        logger.info(f"[Core重启] 使用自定义重启命令: {restart_command}")
        return restart_command
    else:
        tool = check_start_tool()
        if tool == "uv":
            command = "uv run core"
        elif tool == "pdm":
            command = "pdm run core"
        elif tool == "poetry":
            command = "poetry run core"
        elif tool == "python":
            command = "python -m gsuid_core.core"
        else:
            command = "python -m gsuid_core.core"
        logger.info(f"[Core重启] 使用默认重启命令: {command}")
        return command


async def get_restart_sh() -> str:
    args = f"{get_restart_command()} {str(bot_start.absolute())}"
    return _restart_sh.format(str(bot_start.absolute()), args)


async def restart_genshinuid(
    event: Optional[Event] = None,
    is_send: bool = True,
) -> None:
    pid = os.getpid()
    restart_sh = await get_restart_sh()
    with open(restart_sh_path, "w", encoding="utf8") as f:
        f.write(restart_sh)

    if platform.system() == "Linux":
        # os.system(f'chmod +x {str(restart_sh_path)}')
        # os.system(f'chmod +x {str(bot_start)}')
        pass

    now_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))

    if is_send and event:
        await gs_subscribe.add_subscribe(
            subscribe_type="session",
            task_name="[早柚核心] Restart",
            event=event,
            extra_message=now_time,
        )

    await core_shutdown_execute()

    if platform.system() in ("Linux", "Darwin"):
        # In tmux deployments, the GS process is the pane's foreground process.
        # Do not call `tmux respawn-pane -k` directly from this foreground process:
        # killing the pane may also interrupt that tmux client before it completes.
        # Start a detached helper first; the helper waits briefly, then asks the
        # tmux server to respawn this same pane with `uv run core` as foreground.
        tmux_target = os.environ.get("TMUX_PANE") or "gs:0.0"
        restart_command = get_restart_command()
        helper_cmd = (
            "sleep 1; "
            f"tmux respawn-pane -k -t {tmux_target!r} "
            "-c /root/gs/gsuid_core "
            f"{('exec ' + restart_command)!r}"
        )
        subprocess.Popen(
            ["bash", "-lc", helper_cmd],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    else:
        # Windows
        # 加入 timeout /t 2 /nobreak 来等待 2 秒，确保旧进程彻底死亡，文件锁释放
        subprocess.Popen(
            f"taskkill /F /PID {pid} & timeout /t 2 /nobreak > NUL & {get_restart_command()}",
            shell=True,
        )


async def restart_message():
    if update_log_path.exists():
        update_log_path.unlink()

    datas = await gs_subscribe.get_subscribe(
        task_name="[早柚核心] Restart",
    )
    if datas:
        now_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
        data = datas[0]
        await data.send(f"🚀 重启完成!\n关机时间: {data.extra_message}\n重启时间: {now_time}")
        await Subscribe.delete_row(task_name="[早柚核心] Restart")
    else:
        logger.warning("[Core重启] 没有找到[Core重启]的订阅, 无推送消息！")
