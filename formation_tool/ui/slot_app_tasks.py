"""Task execution, log queue, and cancellation helpers for SlotProcessApp."""
import contextlib
import queue
import threading
import time
import traceback
from tkinter import messagebox

from formation_tool.utils import log_utils
from formation_tool.core import task_preflight
from formation_tool.ui import task_confirmations


class QueueWriter:
    """Forward print output into the GUI log queue."""

    def __init__(self, log_queue):
        self.log_queue = log_queue

    def write(self, text):
        if text:
            self.log_queue.put(('log', text))

    def flush(self):
        pass


class SlotAppTaskMixin:
    """Background task runner and GUI log/cancel state helpers."""

    def init_task_state(self):
        self.log_queue = queue.Queue()
        self.worker = None
        self.running = False

    def enter_running_state(self, title):
        self.running = True
        self.status_var.set(f"运行中：{title}")
        self.progress.start(12)
        self.set_buttons_state("disabled")
        self.set_cancel_button_state("normal")
        self.set_config_state("disabled")

    def append_runtime_config_log(self):
        deps = self.task_deps
        runtime = deps.get_runtime_state()
        self.append_log(
            f"当前配置：厂商={runtime['vendor']}，游戏编号={runtime['game_id']}，"
            f"源库={runtime['source_db']}，目标库={runtime['final_db']}，配置库={runtime['config_db']}\n"
        )
        self.append_log(f"采样临时库：{runtime.get('sampling_temp_db')}（默认中转）\n")
        self.append_log(
            "采样后自动镜像："
            + ("开启\n" if runtime.get('sampling_auto_sync_to_target') else "关闭\n")
        )
        external_source = deps.get_external_config_source()
        external_error = deps.get_external_config_load_error()
        if external_source:
            self.append_log(f"数据库配置来源：外部文件 {external_source}\n")
        elif external_error:
            self.append_log(f"外部数据库配置加载失败，使用内置配置：{external_error}\n")
        else:
            self.append_log("数据库配置来源：exe 内置配置\n")

    def append_trigger_weight_config_log(self):
        deps = self.task_deps
        trigger_weights = deps.get_trigger_weights()
        self.append_log(
            f"权重配置：特殊局个位0={trigger_weights['special_0']}，"
            f"特殊局个位1={trigger_weights['special_1']}，"
            f"免费局个位0={trigger_weights['free_0']}，"
            f"免费局个位1={trigger_weights['free_1']}\n"
        )

    def append_sampling_config_log(self, *, append_mode=False):
        deps = self.task_deps
        rebate_rules = deps.get_rebate_rules()
        self.append_log(
            f"采样规则：普通局 {len(rebate_rules.get('1', []))} 条，"
            f"特殊局 {len(rebate_rules.get('2', []))} 条，"
            f"免费局 {len(rebate_rules.get('3', []))} 条，"
            f"ex普通局 {len(rebate_rules.get('6', []))} 条，"
            f"ex特殊局 {len(rebate_rules.get('7', []))} 条，"
            f"ex免费局 {len(rebate_rules.get('8', []))} 条\n"
        )
        self.append_log(
            "采样详细日志："
            + ("开启\n" if deps.get_sampling_detailed_log() else "关闭\n")
        )
        temp_db = getattr(deps, "get_sampling_temp_db", lambda: "")()
        if append_mode:
            self.append_log(
                f"采样方案：补充采样，复制目标库旧表到中转库 {temp_db}，"
                "重排旧 id 后追加新采样数据\n"
            )
        elif getattr(deps, "get_sampling_auto_sync_to_target", lambda: False)():
            self.append_log(f"采样方案：写入中转库 {temp_db} 正式表，完成后自动镜像到目标库\n")
        else:
            self.append_log(f"采样方案：写入中转库 {temp_db} 正式表，目标库不变\n")
        direct_count_modes = deps.get_direct_count_modes()
        if direct_count_modes:
            game_configs = deps.get_game_configs()
            direct_names = [
                game_configs[mode]['name']
                for mode in sorted(direct_count_modes)
                if mode in game_configs
            ]
            self.append_log(f"低数据量直写采样配置：{', '.join(direct_names)}\n")
        direct_count_tiers = getattr(deps, "get_direct_count_tiers", lambda: [])()
        if direct_count_tiers:
            self.append_log(f"直接计数阶梯：{len(direct_count_tiers)} 条\n")

    def append_group_weight_config_log(self):
        deps = self.task_deps
        rules = deps.get_group_weight_rules()
        self.append_log(
            f"group_weight区间：普通局 {len(rules.get('1', []))} 条，"
            f"特殊局 {len(rules.get('2', []))} 条，"
            f"免费局 {len(rules.get('3', []))} 条，"
            f"ex普通局 {len(rules.get('6', []))} 条，"
            f"ex特殊局 {len(rules.get('7', []))} 条，"
            f"ex免费局 {len(rules.get('8', []))} 条，"
            f"ex购买局 {len(rules.get(deps.ex_purchase_mode, []))} 条，"
            f"购买局 {len(rules.get(deps.buy_group_mode, []))} 条\n"
        )
        special_target = deps.get_special_group_target_rtp()
        if special_target is not None:
            self.append_log(f"特殊局 rebate=0 反推目标RTP：{special_target}\n")

    def append_purchase_config_log(self):
        deps = self.task_deps
        self.append_log(f"购买局：{'已开启' if deps.get_buy_group_enabled() else '已关闭'}")
        if deps.get_buy_group_enabled():
            self.append_log(
                f"，购买倍数：{deps.get_buy_group_multiplier()}，"
                f"game_type={deps.get_buy_group_game_type()}，"
                f"source={deps.get_buy_group_source_suffix()}"
            )
        extra_buy_groups = deps.get_extra_buy_groups()
        if extra_buy_groups:
            extra_text = ', '.join(
                f"game_type={item['game_type']} 倍数={deps.format_weighted_rtp(item['multiplier'])} source={item.get('source_suffix', 'free_formation')}"
                for item in extra_buy_groups
            )
            self.append_log(f"\n额外购买局：{extra_text}")
        self.append_log(
            f"\nex模式：game_type=6/7/8，ex倍数：{deps.format_weighted_rtp(deps.get_ex_group_multiplier())}，"
            f"ex购买局：{'已开启' if deps.get_ex_buy_group_enabled() else '已关闭'}"
        )
        if deps.get_ex_buy_group_enabled():
            ex_source = deps.get_ex_buy_group_source_suffix() or "DB配置"
            self.append_log(
                f"，game_type={deps.get_ex_buy_group_game_type()}，source={ex_source}"
            )
        ex_source_suffixes = getattr(deps, "get_ex_source_suffixes", lambda: {})()
        if ex_source_suffixes:
            suffix_text = ', '.join(
                f"{mode}={suffix}"
                for mode, suffix in sorted(ex_source_suffixes.items(), key=lambda item: str(item[0]))
            )
            self.append_log(f"，group_weight后缀覆盖：{suffix_text}")
        self.append_log("\n")

    @staticmethod
    def get_task_log_kind(title, preflight):
        if isinstance(preflight, dict):
            return preflight.get("kind")
        if title == "生成group_weight":
            return "group_weight"
        if title == "生成采样配置":
            return "rebate_config"
        if "采样" in title:
            return "sampling"
        if title == "通用表配置":
            return "common_config"
        return None

    def append_task_header_log(self, title, preflight=None):
        self.append_log(log_utils.section(title) + "\n")
        self.append_runtime_config_log()
        kind = self.get_task_log_kind(title, preflight)
        if kind in {"rebate_config", "sampling"}:
            append_mode = bool(preflight.get("append_mode")) if isinstance(preflight, dict) else False
            self.append_sampling_config_log(append_mode=append_mode)
        elif kind == "group_weight":
            self.append_group_weight_config_log()
            self.append_purchase_config_log()
        elif kind == "common_config":
            self.append_trigger_weight_config_log()
            self.append_purchase_config_log()

    def build_dangerous_task_confirmation(self, title, preflight):
        return task_confirmations.build_dangerous_task_confirmation(
            title,
            preflight,
            deps=self.task_deps,
        )

    def confirm_dangerous_task(self, title, preflight):
        message = self.build_dangerous_task_confirmation(title, preflight)
        if not message:
            return True
        return messagebox.askyesno("确认写入/覆盖", message)

    @staticmethod
    def format_task_duration(seconds):
        seconds = max(0.0, float(seconds or 0))
        if seconds < 60:
            return f"{seconds:.2f} 秒"
        minutes, rem = divmod(seconds, 60)
        if minutes < 60:
            return f"{int(minutes)} 分 {rem:.2f} 秒"
        hours, rem_minutes = divmod(minutes, 60)
        return f"{int(hours)} 小时 {int(rem_minutes)} 分 {rem:.2f} 秒"

    def start_worker_thread(self, title, func, preflight):
        self.worker = threading.Thread(
            target=self.worker_main,
            args=(title, func, preflight),
            daemon=True,
        )
        self.worker.start()

    def run_task(self, title, func, preflight=None):
        if self.running:
            messagebox.showinfo("正在运行", "当前任务还没有结束，请稍后再操作。")
            return
        if not self.apply_selected_config():
            return
        if not self.confirm_dangerous_task(title, preflight):
            self.status_var.set("已取消：用户取消写入操作")
            return

        self.task_deps.clear_cancel_request()
        self.enter_running_state(title)
        self.append_task_header_log(title, preflight)
        self.start_worker_thread(title, func, preflight)

    def worker_main(self, title, func, preflight):
        writer = QueueWriter(self.log_queue)
        ok = True
        error = None
        cancelled = False
        result = None
        preflight_blocked = False
        task_started = time.perf_counter()
        preflight_elapsed = 0.0
        execute_elapsed = 0.0
        with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
            try:
                print(f"开始执行：{title}")
                if preflight is not None:
                    preflight_started = time.perf_counter()
                    report = self.task_deps.run_task_preflight(title, preflight)
                    preflight_elapsed = time.perf_counter() - preflight_started
                    task_preflight.emit_preflight_report(report)
                    if not report.ok:
                        ok = False
                        preflight_blocked = True
                        print(f"执行中断：{title}")
                if not preflight_blocked:
                    execute_started = time.perf_counter()
                    result = func()
                    execute_elapsed = time.perf_counter() - execute_started
                else:
                    result = False
                if result is False:
                    ok = False
                    print(f"执行{log_utils.status_label(False)}：{title}")
                elif isinstance(result, dict) and any(value is False for value in result.values()):
                    ok = False
                    print(f"执行部分失败：{title}")
                else:
                    print(f"执行完成：{title}")
            except self.task_deps.task_cancelled_cls as e:
                ok = False
                cancelled = True
                print(f"任务已取消：{e}")
            except Exception as exc:
                ok = False
                error = {
                    'traceback': traceback.format_exc(),
                    'dialog_title': getattr(exc, 'user_dialog_title', None),
                    'dialog_message': getattr(exc, 'user_dialog_message', None),
                }
                print(error['traceback'])
            finally:
                total_elapsed = time.perf_counter() - task_started
                status = "已取消" if cancelled else "成功" if ok else "失败/中断"
                log_utils.print_section(f"任务摘要：{title}")
                if preflight is not None:
                    print(f"预检查耗时：{self.format_task_duration(preflight_elapsed)}")
                print(f"执行耗时：{self.format_task_duration(execute_elapsed)}")
                print(f"总耗时：{self.format_task_duration(total_elapsed)}")
                print(f"任务状态：{status}")
        self.log_queue.put(('done', title, ok, error, cancelled, result))

    def poll_log_queue(self):
        try:
            while True:
                item = self.log_queue.get_nowait()
                kind = item[0]
                if kind == 'log':
                    self.append_log(item[1])
                elif kind == 'done':
                    if len(item) >= 6:
                        _, title, ok, error, cancelled, result = item
                    else:
                        _, title, ok, error, cancelled = item
                        result = None
                    self.finish_task(title, ok, error, cancelled, result)
        except queue.Empty:
            pass
        self.root.after(100, self.poll_log_queue)

    def append_log(self, text):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def clear_log(self):
        if self.running:
            messagebox.showinfo("正在运行", "任务运行中暂不能清空日志。")
            return
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def finish_task(self, title, ok, error, cancelled=False, result=None):
        self.running = False
        self.task_deps.clear_cancel_request()
        self.progress.stop()
        self.set_buttons_state("normal")
        self.set_cancel_button_state("disabled")
        self.set_config_state("normal")
        if cancelled:
            self.status_var.set(f"已取消：{title}")
        else:
            self.status_var.set(f"完成：{title}" if ok else f"失败：{title}")
        if error:
            dialog_title = error.get('dialog_title') if isinstance(error, dict) else None
            dialog_message = error.get('dialog_message') if isinstance(error, dict) else None
            if dialog_title and dialog_message:
                messagebox.showerror(dialog_title, dialog_message)
            else:
                messagebox.showerror("执行失败", f"{title} 执行失败，详情请查看运行日志。")

    def cancel_current_task(self):
        if not self.running:
            return
        self.task_deps.request_cancel()
        self.status_var.set("正在取消当前任务，请等待当前 SQL 操作结束...")
        self.append_log("\n已请求取消：当前正在执行的 SQL 会先结束，下一步将停止。\n")
        self.set_cancel_button_state("disabled")

    def set_buttons_state(self, state):
        for button in self.buttons:
            if button is self.cancel_button:
                continue
            button.configure(state=state)

    def set_cancel_button_state(self, state):
        if self.cancel_button is not None:
            self.cancel_button.configure(state=state)

    def set_config_state(self, state):
        if state == "disabled":
            for widget, _ in self.config_widgets:
                with contextlib.suppress(Exception):
                    widget.configure(state="disabled")
            if self.add_extra_buy_button is not None:
                self.add_extra_buy_button.configure(state="disabled")
            for row_info in self.extra_buy_rows:
                for widget in row_info.get('widgets', []):
                    with contextlib.suppress(Exception):
                        widget.configure(state="disabled")
            for row_info in getattr(self, 'extra_weight_group_rows', []):
                for widget in row_info.get('widgets', []):
                    with contextlib.suppress(Exception):
                        widget.configure(state="disabled")
            return
        for widget, enabled_state in self.config_widgets:
            with contextlib.suppress(Exception):
                widget.configure(state=enabled_state)
        if self.add_extra_buy_button is not None:
            self.add_extra_buy_button.configure(state="normal")
        for row_info in self.extra_buy_rows:
            for widget in row_info.get('widgets', []):
                with contextlib.suppress(Exception):
                    widget.configure(state="normal")
        for row_info in getattr(self, 'extra_weight_group_rows', []):
            for widget in row_info.get('widgets', []):
                with contextlib.suppress(Exception):
                    widget.configure(state="normal")

    def on_close(self):
        if self.running:
            self.task_deps.request_cancel()
            messagebox.showinfo(
                "正在取消",
                "已请求取消当前任务，请等待当前 SQL 操作结束后再关闭窗口。",
            )
            return
        self.root.destroy()
