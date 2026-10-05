"""Shared task budget and deterministic no-progress detection."""
from contextvars import ContextVar
import hashlib
import json
from fei import config

current_budget = ContextVar("fei_runtime_budget", default=None)

class BudgetExceeded(RuntimeError):
    pass

class TaskBudget:
    def __init__(self):
        self.tool_calls = 0
        self.requests = 0
        self.tokens = 0
        self.estimated = False
        self.cache_hit = 0
        self.cache_miss = 0
        self.cache_reported_requests = 0
    def before_request(self, estimate, output_limit):
        if self.requests >= config.MAX_MODEL_REQUESTS:
            raise BudgetExceeded("已达到任务共享模型请求上限，已停止继续调用。")
        if self.tokens + estimate + output_limit > config.MAX_TASK_TOKENS:
            raise BudgetExceeded("任务共享 token 预算不足以继续请求，已停止继续调用。")
        self.requests += 1
    def before_tool(self):
        if self.tool_calls >= config.MAX_TASK_TOOL_CALLS:
            raise BudgetExceeded("已达到任务共享工具调用上限，剩余调用未执行。")
        self.tool_calls += 1
    def record(self, usage, prompt_estimate, output):
        if usage is not None:
            get = usage.get if isinstance(usage,dict) else lambda key,default=None:getattr(usage,key,default)
            hit = get("prompt_cache_hit_tokens")
            miss = get("prompt_cache_miss_tokens")
            prompt = get("prompt_tokens")
            if hit is None:
                details = get("prompt_tokens_details")
                if details is not None:
                    hit = details.get("cached_tokens") if isinstance(details,dict) else getattr(details,"cached_tokens",None)
            if hit is not None and (miss is not None or prompt is not None):
                hit = max(0,int(hit))
                miss = max(0,int(miss)) if miss is not None else max(0,int(prompt)-hit)
                self.cache_hit += hit
                self.cache_miss += miss
                self.cache_reported_requests += 1
            used = get('total_tokens')
            if used is None:
                prompt, completion = get('prompt_tokens'), get('completion_tokens')
                if prompt is None or completion is None:
                    self.estimated = True
                used = (prompt_estimate if prompt is None else prompt) + (len(str(output).encode('utf-8')) if completion is None else completion)
            self.tokens += max(0,int(used))
        else:
            self.estimated = True
            self.tokens += prompt_estimate + len(str(output).encode('utf-8'))
    def snapshot(self):
        return {"tool_calls":self.tool_calls,"tool_limit":config.MAX_TASK_TOOL_CALLS,"requests":self.requests,"tokens":self.tokens,"contains_estimates":self.estimated,
                "request_limit":config.MAX_MODEL_REQUESTS,"token_limit":config.MAX_TASK_TOKENS,
                "cache_hit_tokens":self.cache_hit,"cache_miss_tokens":self.cache_miss,
                "cache_reported_requests":self.cache_reported_requests,
                "cache_hit_rate":self.cache_hit/(self.cache_hit+self.cache_miss) if self.cache_hit+self.cache_miss else None}

class LoopWatch:
    def __init__(self):
        self.counts = {}
        self.errors = 0
        self.warning = None
    def observe(self,name,args,result,error):
        self.warning = None
        text=str(result)
        if error is None and name in {'write_file','edit_file','revert_change','delegate_task'} and not text.startswith('No changes'):
            self.counts.clear()
            self.errors=0
            return None
        fingerprint = hashlib.sha256(json.dumps([name,args,text,error is not None],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        self.counts[fingerprint]=self.counts.get(fingerprint,0)+1
        self.errors=self.errors+1 if error else 0
        if self.counts[fingerprint] == config.REPEAT_LIMIT - 1:
            self.warning = "相同调用已重复且结果未变化；请改用其他方法或报告无法继续，不要重复调用。"
        if self.counts[fingerprint] >= config.REPEAT_LIMIT:
            return f"工具 {name} 在没有修改进展时重复相同参数和结果 {self.counts[fingerprint]} 次，已停止无效循环。"
        if self.errors >= config.CONSECUTIVE_ERROR_LIMIT:
            return f"连续 {self.errors} 次工具失败，已停止无效重试。"
        return None
