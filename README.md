# fei

轻量终端 agent harness：一个 while 循环 + 工具 + 会话。

## 运行

```bash
pip install -e .
copy .env.example .env   # 填入 FEI_API_KEY
fei                      # 或 python -m fei
```

## 结构

依赖方向自上而下；横线以下是核心层，不知道任何接口层的存在：

```
cli.py        接口层：REPL、流式打印
session.py    会话持久化（~/.fei/sessions/*.jsonl，可恢复）
approval.py / permission.py 权限模式、会话授权与危险命令守卫
──────────────── 以下为核心，与终端 / Web 无关 ────────────────
loop.py       核心 agent 循环：模型、工具、预算、任务完成与子任务调度
context.py    上下文管理：用 API usage 统计 token，请求前检查预算并压缩历史
tools/        工具注册表（bash / read_file / write_file）
llm.py        OpenAI 兼容客户端封装（智谱 / DeepSeek / ... 通用）
config.py     .env 加载、常量、Git Bash 路径探测
tests/        test_context.py 无 API 单测；smoke_e2e.py 真实 API 冒烟
```

## 设计规则

1. **核心不做 I/O**：`loop.run_task(client, messages, confirm, notify,
   on_text, stats)` 的所有交互都由接口层通过回调注入。以后要 Web 界面，
   只需新增一个 `api.py` 用 FastAPI 包住 `run_task`，核心零改动。
2. **工具报错不抛出**：错误文本作为工具结果喂回模型，模型自己换思路重试。
3. **输出截断**：大工具结果保存全文，上下文仅放 `MAX_TOOL_OUTPUT` 范围内的首尾预览和路径；
   `MAX_TURNS` 防死循环。
4. **任务内压缩**：每次请求前检查预算，保留原始当前用户请求和最近两个完整消息块；tool_calls/tool 不拆散。参考 API usage，并使用 UTF-8 字节量做保守预估，预估不是精确 token 数。
5. **安全策略：权限模式与危险命令守卫**：`rm -rf /`、`mkfs`、`dd if=` 等
   命中即拒绝、不交互确认，`FEI_ALLOW_DANGEROUS=1` 可整体关闭。
   `/permission auto` 按目录及会话授权；`read` 限制为只读工具；`full` 免工具确认，危险守卫仍生效。
   命令使用当前用户的操作系统权限；这些模式不提供操作系统沙箱。
6. **控制台只显示重要的**：默认只打印最终回答与错误事件（`error`）；
   工具过程仍然全量写入会话 JSONL，要看过程开 `FEI_VERBOSE=1`
   或翻会话文件。核心层照发全部事件，展示策略属于接口层。

## 测试

```bash
python tests/test_context.py   # 无 API：压缩切点逻辑 + 危险命令拦截
python tests/test_events.py    # 无 API：成功静默 / 失败必报 error 事件
python tests/smoke_e2e.py      # 真实 API：流式 + 工具循环 + 压缩后可续聊
```

## 演进路线

- [x] **Step 0-1** 最小对话循环
- [x] **Step 2-3** tool calling + 工具注册表（run_bash / read_file / write_file）
- [x] **Step 4** 上下文压缩（`context.py`）
- [x] **Step 5** 流式输出（stream 增量拼装 tool_calls）
- [x] **Step 6** 权限加固（`permission.py`）
- [x] **Step 7 扩展**：slash command、skills、MCP、只读探索及受限执行子 agent。
- [ ] 后续：子任务接收/撤销、执行隔离、真实模型成本基线与中断恢复完善。

## 加一个新工具的步骤

1. 在 `fei/tools/` 下新建文件，定义一个 `Tool`（name / description /
   JSON Schema / handler，可选 guard 拦截器）；
2. 在 `fei/tools/__init__.py` 里 `register` 一行。

## 会话恢复与失败处理

每次任务保存完整 `.jsonl` 记录和实际上下文 `.state.json`，压缩后同步更新状态。使用 `/resume "会话路径"` 恢复到新会话；旧版仅有 JSONL 的记录不能直接恢复。`/clear` 创建独立新会话。命令在 `FEI_WORKDIR` 执行，非零退出码作为错误返回给模型。API 失败或 Ctrl+C 中断后仍可继续输入。

回归测试：`python -m unittest discover -s tests -p test_reliability.py -v`。

## 代码搜索与局部修改

新增 `search_code(pattern, path=".", glob="", regex=False)`：默认按字面量搜索，返回路径和行号，遵循忽略规则。需要 PATH 中有 ripgrep (`rg`)，结果最多显示每文件 100 处匹配，并对总输出截断。

新增 `edit_file(path, old_text, new_text, replace_all=False)`：精确替换已有 UTF-8 文件中的文本；找不到或存在多个匹配时拒绝修改，批量替换必须显式指定 `replace_all=True`。保留 BOM 和换行，支持删除匹配内容；拒绝二进制及超过 5 MiB 的文件。模型应先搜索、读取，再局部编辑和验证。

测试：`python -m unittest discover -s tests -p "test_*.py" -v`。

## 权限、请求可靠性和任务记录

工作目录内读取和搜索自动执行；目录外读取、所有写入/编辑/命令执行均需逐次输入 `y` 确认。危险命令先硬拦截。无确认回调时默认拒绝需要权限的操作。确认界面显示完整路径、命令或修改内容。此机制不是操作系统沙箱，批准的命令仍具有当前用户权限。

`FEI_REQUEST_TIMEOUT` 默认 60 秒，是客户端请求超时；`FEI_REQUEST_RETRIES` 默认 2，使用 SDK 对临时连接错误和可重试状态码有限重试。已开始消费的流中断时停止本次任务，不重新播放流、不重跑工具。

每次任务另存 `.tasks.jsonl`：目标、起止时间、实际工具参数/结果/错误和最终回答。`returned` 只表示模型已返回回答；验证字段默认 `not_independently_verified`，不会把模型结束当作测试通过。原始工具结果保留供核对。

## 长任务上下文管理

每次模型请求前检查 `FEI_COMPACT_TOKENS` 预算。使用 API 最近一次 prompt usage 加新消息增长量，同时按消息、工具 schema 的 UTF-8 字节量保守预估；这不是精确 tokenizer 计数，可能提前触发压缩。预算应按所用模型上下文大小设置，并预留响应空间。

压缩保留 system、当前原始用户要求以及最近两个完整消息块（一次 assistant 多工具调用及所有结果算一个块），较早记录按有限大小分块整理成工作备忘。备忘包括约束、文件修改、实际验证、失败、待办和输出记录路径。重复压缩会继续整理已有备忘。摘要内容由模型生成，仍可能遗漏或误述；原始消息和工具证据独立保存供核对。

大工具结果的完整内容保存在会话同名 `.outputs` 目录，模型上下文保留首尾预览及绝对路径。可用 `read_file` 的 offset/limit 分页查看；目录外记录仍遵循读取确认规则。命令错误、选定文件片段和搜索结果不再提前按字符截断。搜索仍最多返回每文件 100 处匹配，应收窄搜索范围以取得其他匹配。

消息产生后立即写入 JSONL，每轮完整工具结果及压缩后保存状态；任务记录包含压缩备忘。若摘要为空、不能缩小上下文或保留部分仍超过预算，停止当前任务并保留原上下文，而不是发送明显超预算的请求。已执行工具不会因为压缩而重跑。

离线验证覆盖多轮任务自动压缩、原始目标保留、多工具结果配对、压缩后会话恢复、完整日志和大输出尾部错误保留。未进行真实模型 API 长任务测试。

## 生命周期 Hook

`HookRegistry` 支持按注册顺序运行多个同步处理器，`register` 返回注销函数。事件包含 `task_start/task_end`、`before_model/after_model`、`before_tool/after_tool`、`before_compact/after_compact`，以及 `message/checkpoint/notice`。`after_model` 与 `after_tool` 提供耗时；后置事件在操作正常返回后触发，工具错误也会进入 `after_tool`，模型或压缩异常通过 `task_end` 的失败状态记录。

`before_*` 处理器返回 `False` 或拒绝原因字符串可阻止操作；返回 `None` 表示继续。执行前处理器报错默认阻止操作。工具 Hook 拒绝会作为工具错误结果回填给模型。已有危险命令拦截、路径和权限检查在 Hook 后独立执行，不能被 Hook 返回值绕过。

每个处理器收到独立数据快照，修改快照不会修改真实消息或工具参数。普通观察处理器报错会记录并继续，`critical=True` 的持久化处理器报错则停止任务。`KeyboardInterrupt` 正常传播，任务结束事件仍触发。每次任务复制注册表，兼容回调适配不会累积到共享注册表。

任务记录逻辑位于 `fei/recording.py`，CLI 通过 Hook 注册消息日志、检查点保存和显示；旧 `notify/on_message/checkpoint/task_record` 参数通过适配器保持兼容。`confirm` 和 `output_writer` 是有返回值的执行依赖，继续显式注入。

示例：

```python
from fei.hooks import HookRegistry
from fei.loop import run_task

hooks = HookRegistry()
hooks.register("after_tool", lambda event: print(event.data["name"], event.data["elapsed"]))
hooks.register("before_tool", lambda event: "禁止此工具" if event.data["name"] == "run_bash" else None)
run_task(client, messages, hooks=hooks, confirm=confirm)
```

## 主动上下文压缩工具

第六个工具 `compact_context(reason="")` 允许模型主动请求压缩，无需用户确认。可在历史干扰判断或进入新阶段时调用。工具返回“请求已接受”，而非压缩成功；完整批次的全部工具调用和结果回填后，使用现有压缩逻辑和 before_compact/after_compact Hook 执行压缩，并增加一条明确的实际结果消息（成功、跳过、失败或拒绝）。同批多次请求合并为一次压缩。历史不足会跳过；摘要失败会保留上下文继续，后续自动预算检查仍生效。关键日志/状态保存 Hook 失败仍中止任务。

## 修改 diff 与回退

现在共 8 个工具。新增 `show_changes(change_id="")`：不带 ID 列出当前工作目录的工具修改记录，带 ID 查看该次修改的原始前后 diff。新增 `revert_change(change_id)`：逐次确认后恢复该次修改前的原始字节；新建文件则删除该文件。若文件当前内容不等于记录的修改后内容，拒绝回退，避免覆盖后续修改。连续修改同一文件时按最新到最旧顺序回退。

`write_file` 和 `edit_file` 返回 change_id，修改前备份原始字节到工作目录 `.fei-changes`，单文件上限 5 MiB。恢复保留 BOM、换行和文件模式。此记录只覆盖这些工具的写入，不能撤销 run_bash 直接修改的文件或外部副作用；show_changes 展示记录的前后差异，不是实时 Git diff。无变化不产生记录。记录跨进程保存，应保留 `.fei-changes` 以支持回退。

## 可重复的真实模型评测

从项目根目录运行：

```bash
python -B -c "import runpy; runpy.run_path('tests/eval_tasks.py', run_name='__main__')"
```

使用当前 API 配置，会产生请求费用。两个任务分别修复 clamp 边界逻辑、实现布尔字符串解析；只允许修改独立目录中的 solution.py 和运行固定测试命令，拒绝修改测试。结束后独立执行测试并比对测试文件，报告通过与否、工具次数、耗时及 token usage；不把模型说完成当作成功。

报告、代码和任务记录保存在 `work/evals/<时间>/`。2026-10-04 首次真实模型评测：2/2 通过，测试文件均未修改，工具调用分别 5 次和 6 次，耗时约 5.1 秒和 6.0 秒。这仅是两个小型 Python 任务的初步验证，不代表大型项目成功率。

## 参数校验、项目规范、完成证据与命令管理

工具参数在执行前按当前工具 Schema 校验：必填、类型、未知字段、enum、字符串长度、数值和数组边界。拒绝布尔值冒充整数以及非有限数值。校验器实现的是本项目使用的 JSON Schema 子集，不支持任意外部 Schema 的全部特性。读文件 offset 必须 >=1，limit 为 1..10000；命令 timeout 为 1..600 秒。无效参数作为工具错误回填给模型，不进入执行确认。

每个任务自动加载 FEI_WORKDIR 的 AGENTS.md；访问具体路径时再加载该路径目录链内适用的 AGENTS.md，标注来源与作用范围。工作目录之外的规则不会隐式加载。缓存根据修改时间和大小刷新，文件删除后移除规则；每文件最多 64 KiB，总规则最多 128 KiB。若编辑时首次发现目录规则，本次编辑被拒绝，模型先读取新加载的规则再重试。项目规范不能覆盖用户明确要求。

新增第九个工具 finish_task(summary, completed, remaining, verification_ids, status)。status 为 verified/unverified/incomplete。编辑、写入或回退后，纯文本回答不能直接完成任务：会提醒提交，连续两次未提交则结束为 incomplete，保留修改。解释/读取类任务仍可直接回答。

验证使用 run_bash(command=..., purpose="verification")；命令结果明确给出实际记录 ID。verified 必须引用当前任务中真实存在、执行成功且晚于最后工具修改及其他普通命令的验证 ID，不能引用失败、旧任务或编造的 ID。有待办应提交 incomplete；未做验证可提交 unverified。证据在任务状态中独立保存，压缩不会清除。verified 表示关联验证命令执行成功，不能证明检查本身充分，也不能证明代码完全正确；shell 直接修改文件仍不属于工具修改追踪范围。

run_bash 现在持续保存完整 stdout/stderr 到工作目录 `.fei-results/command-*.log`，启动时显示记录路径，运行期间约每两秒报告耗时和最新输出。timeout 默认 120 秒，可设 1..600 秒；超时和 Ctrl+C 会清理进程树。Windows 使用 Job Object，POSIX 使用独立进程组。此工具是前台命令，结束时清理它的后台子进程；尚未提供独立后台任务 ID/查询接口。暂停或中断不自动重跑命令。

回归测试：63 项 unittest 与原有 8 项脚本检查通过，包括 Windows 实际子进程超时清理、Ctrl+C 路径清理、目录规范刷新、伪造/失败/过期验证 ID 拒绝和结构化完成提交。

2026-10-04 最新真实模型评测：clamp 修复与 parse_bool 实现均通过独立代码测试并提交 completed_verified，测试文件未修改；分别 7/9 次工具调用、约 6.84/8.04 秒。报告位于 `work/evals/20261004-220228/report.json`。之前一次评测发现模型无法正确引用验证 ID，修复后工具结果显式显示 ID，并在校验错误中提示可用 ID。仅两项小任务，不代表大型项目成功率。

## 扩展真实任务评测（六项）

`tests/eval_cases.py` 定义六个独立 Python 小项目：clamp 修复、布尔解析、跨文件数量与折扣修复、重试延迟功能、先观察失败再修复的数字解析、压缩后保留约束的标签规范化。最后一项预置明确标注为 synthetic 的历史消息以触发预算压缩，并不代表真实大型仓库探索。

`tests/eval_tasks.py` 逐个创建 `work/evals/<时间>/<任务>/`，保护测试和 AGENTS.md，只允许修改指定源文件与执行固定验证命令。检查初始代码确实失败；结束后独立运行测试，比对保护文件，要求 completed_verified；纠错用例额外要求真正的测试失败→修改→验证成功，长上下文用例额外要求发生压缩。拒绝执行不算测试失败。记录调用数、工具错误、耗时、token、压缩次数和各项评分。

评分只适用于这些指定用例，不代表通用项目成功率。评测限制由工具 Hook 实现，不是操作系统沙箱。未知 API 费用不做价格估算，报告保留 token usage；API 不可用时停止继续发送请求。

离线测试共 66 项，另有原有 8 项脚本检查。新增检查验证所有初始用例失败、参考实现通过，以及纠错评分不会把权限拒绝误判为实际测试失败。

## 扩展评测发现的上下文问题与修复

首次六任务评测为 5/6：普通任务、跨文件任务及失败后纠错通过；长上下文在生成空摘要时停止，未覆盖原始消息。摘要请求现在默认允许 4096 个输出 token，遇到空内容或 finish_reason=length 时仅重试一次，预算提高到 8192；连续失败仍拒绝压缩。非空但被截断的摘要也不能作为成功备忘。

备忘作为带标记的历史数据放在原始当前用户请求之前，保留最近完整工具消息块。这样没有当前工具尾部时，压缩后的请求仍以当前用户消息结束。重复压缩继续整理旧备忘。

当前推理模型要求保留响应的 reasoning_content 扩展字段。适配层对非流式和流式响应保留此字段到实际历史消息，终端流式显示只输出回答文本，不显示该字段。受控长上下文用例使用明确标注为 synthetic 的完整工具消息对，不将预置历史算成本任务真实执行证据。

新增观察事件 after_summary，提供摘要请求耗时、usage 和 finish_reason；评测同时统计普通模型请求与摘要请求 token。旧报告中普通请求统计不包含压缩请求，不能用于对比压缩总费用。72 项离线测试通过，包含空摘要恢复、截断摘要拒绝、原始消息保留、消息布局和模型字段兼容。

长上下文最终复测通过：发生 2 次压缩，约 42.78 秒，6 次工具调用，代码测试、受保护文件比对和 completed_verified 均通过。首次 5/6 与修复后长上下文 1/1 的对照汇总位于 `work/evals/evaluation-summary-20261004.json`；这是首次运行与针对性复测的合并观察结果，不是同一次六项全通过运行。

## 项目定位与统一验证（现有 12 个工具）

新增 list_directory(path=".", depth=2, limit=200) 查看相对目录结构；find_files(pattern, path=".", depth=20, limit=100) 按文件名或相对路径模式查找。支持 `*config*`、`tests/**/*.py`（** 匹配零层或多层目录）。默认跳过隐藏项、node_modules/venv/cache/build 等目录和符号链接，可显式启用隐藏项/忽略目录；符号链接始终不遍历。最多扫描 10000 项或约 5 秒，输出超限明确提示；深度上限同样会限制结果。目录外访问仍需确认。

新增 verify_project(checks=[...])：读取工作目录 .fei.json，省略 checks 执行全部已配置检查。缺少配置会提示错误，不猜测测试/构建命令。配置必须 version=1，checks 包含 1..20 个命名检查，每项有 category=test/lint/build、argv 字符串数组和可选 timeout（1..600秒）。特殊 argv 元素 `{python}` 替换为当前解释器。argv 直接执行，不经过 shell，重定向和管道不是配置语法。

示例配置在 `.fei.example.json`。确认内容适合项目后复制为 `.fei.json`，例如：

```json
{
  "version": 1,
  "checks": {
    "test": {
      "category": "test",
      "argv": ["{python}", "-B", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"],
      "timeout": 120
    }
  }
}
```

执行前展示准确 argv、类别、超时和工作目录，逐次确认一次所选检查计划；配置摘要与已确认计划绑定，配置在确认后变更则拒绝执行。危险命令在检查阶段和真正执行前都拦截。各项分别记录 passed/failed/error、退出码和完整输出，普通失败继续运行其他所选检查，中断则停止。命令仍具有当前用户权限，argv 执行不是沙箱。

verify_project 返回实际调用 ID，finish_task 可以引用；存在 .fei.json 的项目，verified 必须引用 verify_project，不接受 run_bash 记录替代。只验证所选检查，成功不代表未选择的测试或代码完全正确；检查内容由项目配置与用户确认决定。

评测套件现在共 7 项，新增分层项目定位与统一验证任务。首次真实验收通过：实际调用 list_directory、find_files 和 verify_project，跨文件代码测试和完成证据通过；测试、AGENTS.md 和 .fei.json 保持原样，15 次工具调用、约 10.19 秒。报告在 `work/evals/20261004-222039-969360/report.json`。

新增目录/配置/权限/证据检查，并覆盖确认后配置变更与新目录规则在同批工具中未审阅时拒绝修改。符号链接创建测试在本机无权限时跳过，扫描实现本身拒绝跟随符号链接。


## MCP 接入（stdio 第一版）

安装可选依赖：`.venv\Scripts\python.exe -m pip install -e ".[mcp]"`。
第一版固定 SDK 1.x 维护分支（`mcp>=1.30,<2`），不混用 v2 API。
将 `.fei-mcp.example.json` 复制为工作目录的 `.fei-mcp.json` 后启动 fei。
示例启动 `examples/readonly_mcp.py`，提供 project_info、root_files 两个只读工具。
实际配置默认不存在，因此不会自动启动外部服务。

配置 version=1，servers 为服务名称到 stdio 配置的映射，支持 command、args、timeout（1..120 秒，默认30）。
command 的 `{python}` 替换为 fei 当前解释器；args 直接传递，工作目录为配置目录，不经过 shell。
启动前展示完整 argv 和目录并确认，每次 MCP 工具调用也需确认，不根据服务提供的 readOnlyHint 自动放行。
服务具有当前用户权限，协议连接不提供操作系统沙箱。环境沿用 SDK 默认环境白名单，不自动传递 fei 的 API Key。

工具发现支持分页，注册名称采用 `mcp__服务__工具` 命名空间，特殊字符或超长名称加哈希防碰撞。
外部 JSON Schema 保留原样，通过完整校验器支持 anyOf、oneOf、$defs 和本地 $ref；不联网读取外部引用。
MCP 调用沿用 before_tool/after_tool、权限、输出落盘和任务记录；服务 isError 作为失败返回模型。
支持文本和 structuredContent；图片/音频等仅给出类型提示，不传递二进制数据。
异步连接由专用线程桥接到同步循环，同一异步任务管理连接进入、调用、退出；超时或中断关闭连接且不重试工具。
CLI 退出清理连接并移除动态注册。服务失败或超时后本会话不自动重连，需要重启 fei。
本版不支持 HTTP、Resources、Prompts、动态 tools/list_changed 或 OAuth。

测试包含真实 stdio 工具发现/调用、超时清理、注册恢复、Schema、来源权限和通过 Agent 循环的 Hook 拦截。

## 任务计划

`update_plan(steps=[{"id":"inspect","title":"定位问题","status":"in_progress"}])`
替换当前任务的完整计划，最多 30 步，ID 唯一，最多一个 in_progress；其他状态为 pending/completed。
可根据新发现修订，steps=[] 清空旧计划。计划更新通过 progress 事件显示。
计划保存在 TaskState，并以独立 system 快照进入 .state.json；压缩原样保留，/resume 后未完成计划恢复。
已提交 verified/unverified 的计划关闭，不约束下一轮；incomplete 的计划继续保留。
未完成步骤要求 finish_task 使用 incomplete，并在 remaining 说明原因。计划全部完成不能替代实际验证证据。
恢复仅恢复计划，不恢复旧任务验证证据；恢复后若要声明 verified，需要重新验证。

## CLI 会话权限（替代任务内授权）

`/permission` 查看当前模式；`/permission read|auto|full` 切换并清除授权。
默认 auto：工作区文件读写自动执行；普通 shell 命令首次审批时可选 y=一次、s=本会话、N=拒绝。
目录外读写按规范化真实目录及其子目录授权；读授权不能允许写，写授权包含读取。
MCP 按来源和具体工具授权，项目验证按准确检查计划授权；删除/回退在 auto 下仅单次审批。
read 禁止命令、文件修改与外部工具；full 免工具审批，已有危险守卫仍优先执行。
命令授权具有当前用户权限，可能访问工作区外文件与网络；模式不是操作系统沙箱。
会话授权不会因下一条输入失效，但退出、/clear、/resume 或模式切换都会清除；不保存永久授权。
审批记录独立保存为会话旁的 .permissions.jsonl，不进入模型上下文，也不用于恢复授权。
没有审批接口、接口失败或用户取消时，需要审批的操作均拒绝。核心旧 confirm 回调仍兼容。
Windows 文件工具支持 C:/...、/c/... 和 ~，拒绝含糊的 /Users/... 根相对路径。

## 控制台显示

默认隐藏工具进度、PID、日志路径与计划更新，错误仅显示简短提示；模型回答与最终文字结果正常显示。
完整工具记录仍保存在会话和命令日志中，`FEI_VERBOSE=1` 显示完整过程。

## 只读 SubAgent 与本地 Skills

`explore_code(question)` 使用同一模型、独立上下文探索代码，主会话只收到结果；问题需包含路径与约束。
子 Agent 只暴露 read_file/search_code/list_directory/find_files/get_environment，即使 full 也不能写、执行 shell、调用 MCP 或递归委派。
最多 4 次探索/任务、8 轮模型调用/探索；结果明确标记为发现而非验证证据，子任务记录保存在任务日志，全文由 output_writer 保存。
子 Agent 继承调用方权限服务和 guard hooks，目录外读取仍按会话策略裁决。初版同步执行，不做后台并行或自动恢复子任务。

`list_skills()` 发现 `.fei/skills/<name>/SKILL.md`；`load_skill(name)` 按需加载纯文本指引，不执行脚本。
名字限制为字母/数字/下划线/连字符，路径不允许越出技能根目录。单份限 16 KiB，最多 4 份、合计 24 KiB。
加载后作为独立上下文保留，压缩不改写；会话恢复保留已加载文本。修改技能文件后再次 load_skill 刷新。
自带 python-check 示例；技能指引服从用户指令、权限与只读边界。

`get_environment()` 提供真实桌面路径（读取 Windows 桌面重定向配置）、主目录、工作目录和 shell。
桌面任务不再需要用多条命令猜位置；模型提示要求沿用已明确的路径，禁止找不到目录就默默换到工作目录。

## 执行型子 Agent

`delegate_task(task, files, verification_argv, timeout=120)` 串行执行明确实现任务。
files 是工作区内准确文件列表（最多 20），拒绝目录、隐藏路径和越界符号链接。子 Agent 可读代码、修改授权文件、维护计划，并通过 run_check 执行委派时固定的验收 argv；不能使用任意 shell、MCP 或递归委派。
验收 argv 直接执行，{python} 替换当前解释器；auto 模式展示完整委派合同并单次确认，full 免确认，read 拒绝。
文件范围约束作用于文件工具；验收程序使用当前用户权限，可能有副作用，并非沙箱。
修改直接落盘，返回真实 change_id/diff、验收记录和完成状态；失败后的修改也保留，可用 revert_change 逐条回退。
主 Agent 需要检查差异并独立验证整体任务，不得把子任务检查 ID 作为主任务证据。子任务最多 16 轮，每个主任务最多 4 个子任务（含探索）。

## 多行任务输入

内置 input() 每次只读取一行，直接粘贴多行会触发多个任务。先输入 `/paste`，粘贴完整任务，再单独输入 `/end`，会保留空行和缩进，一次执行；`/cancel` 或中断不执行。
也可 `/taskfile examples/worker_task.txt` 从 UTF-8 文件读取完整任务。文本上限 64 KiB。
执行型子 Agent 示例任务已放在 examples/worker_task.txt，使用独立 worker_demo_case 目录；目录存在时停止，不清空已有文件。

## 任务状态与评测

`/status` 只读显示最近任务、当前计划、子任务状态、记录的修改文件和主任务最近验证；不会请求模型或执行工具。
/clear 清除状态，/resume 恢复源会话旁的最近任务记录；权限仍重新授权。
最近验证执行成功不等于最新修改已验收，最终完成状态单独展示。
真实模型评测从根目录运行 `python -c "import runpy; runpy.run_path('tests/eval_tasks.py', run_name='__main__')"`，新增 delegated_cross_file，共 8 个案例。
该案例要求子 Agent 完成两个文件修复、返回真实验收记录，父 Agent 不直接修改、独立验证，测试与项目指令保持不变。
真实模型评测使用已配置外部 API，会发送案例文件内容并产生模型费用，必须显式运行。

本地任务级评测：`python tests/eval_workflows.py`，不调用外部模型。
覆盖跨文件委派、真实检查失败后修复、越界修改拒绝、父任务独立验证、中断恢复新验证，以及 /status 不调用模型。
模型决策为预置脚本，文件修改与验收命令实际执行；证明 harness 的执行约束与恢复流程，不代表真实模型任务成功率。
报告保存在 work/evals/*-workflows/report.json。

## Token 与无效循环控制

单个主任务、探索/执行子 Agent、压缩请求共享：60 次模型请求、200000 累计 token、120 次工具调用。
请求前按预计输入和最大输出检查余额；有 API usage 时使用实际消耗，无 usage 时保守估算并标记。不是计费硬上限，SDK 内部重试与服务端未返回 usage 的失败请求无法精确计费。
单次常规模型输出最多 4096 tokens；read_file 默认读取 200 行，更多内容显式分页。
上下文预算有 API prompt_tokens 时以该值加新增内容的保守估算校准，缺少 usage 时仍使用字节上界；不把所有 UTF-8 字节永久当实际 token。
同参数、同结果且没有实际修改进展的工具调用：第二次提示换方法，第三次停止；连续 6 次失败也停止。实际文件修改后允许重新验证。
停止时保留修改和完整调用/结果配对，状态为 loop_detected 或 budget_exceeded，不伪造完成。
/status 可查看共享消耗。配置项见 .env.example；预算跨子任务共享，但每次用户输入新主任务重新计算。

## 请求前缀与缓存统计

计划、已加载 Skills 和项目规则的更新只追加新快照，不再每轮重写历史前缀；内容不变不新增消息。最新快照覆盖同类旧快照。
压缩时只保留每类最新快照，建立新的前缀；压缩可能暂时降低缓存命中，但不为命中率保留无用历史。
工具 schema 按名称稳定排序，主 Agent、探索/执行子 Agent 各自使用固定能力集合。
共享预算汇总 DeepSeek prompt_cache_hit_tokens/prompt_cache_miss_tokens，兼容 prompt_tokens_details.cached_tokens；/status 显示当前主任务（含子任务和压缩）的命中量和加权命中率。
服务端未提供缓存字段时显示未知，不当成 0%；统计比例仅覆盖返回缓存字段的请求。实际命中还受服务端缓存建立和淘汰影响。

## 开发验证与安装

需要 Python 3.10 或更新版本。搜索工具需要 PATH 中的 `rg`（ripgrep）；Windows 推荐安装 Git for Windows，让命令工具使用 Git Bash。MCP 是可选依赖：`pip install -e ".[mcp]"`。

```bash
python -m unittest discover -s tests -p "test_*.py"
python tests/eval_workflows.py
python -m pip wheel . --no-deps --wheel-dir dist
python scripts/check_install.py dist
```

GitHub Actions 在 Windows/Linux、Python 3.10/3.12 上运行回归、离线任务评估及 wheel 安装检查。检查从工作区外加载已安装包并启动控制台入口，不发送模型请求。离线任务评估使用脚本化模型决策，不能代表真实模型成功率。

`check_install.py` 默认创建独立虚拟环境并安装 wheel 依赖；本地无网络时可加 `--reuse-dependencies`，复用当前解释器的依赖，仅检查包安装和入口。这种方式不能证明依赖可以从零下载安装。

`.fei/skills/` 是项目内技能示例，随 Git 仓库提供；wheel 仅包含 Python 包。通过 wheel 安装后，需要自行在工作区创建技能目录。`.env`、运行日志、备份及手工演示目录不会纳入版本控制。

## 子任务结果审阅

执行子任务返回后，主 Agent 用 `review_worker(subtask_id, decision, reason)` 显式接收或拒绝。接收要求子任务完成且验证通过，文件仍与记录一致；主任务仍需独立验证。拒绝先检查整批修改链，再按逆序恢复原字节或删除该子任务新建的文件。文件被后续修改或路径被重定向时，拒绝覆盖；`/status` 显示 pending/accepted/rejected。

修改仍直接落盘，接收不是合并事务。外部并发写入或 I/O 故障可能使撤销部分完成，错误会保留在审阅记录中；验收命令的副作用不受文件变更记录覆盖。存在待审阅执行子任务时，完成提交必须标记 incomplete；主 Agent 接收或拒绝后才能提交完成。
