# Python 检查流程

用于修改 Python 代码后选择相关验证。

1. 阅读项目配置和相关测试，保持用户要求的接口和行为。
2. 有 .fei.json 时优先 verify_project；否则选择已有测试命令，用 run_bash(purpose="verification")。
3. 没有测试时做与修改相关的最小行为检查，不把语法检查说成行为验证。
4. 先完成修改和清理，再执行最终验证；验证后直接提交 finish_task。
5. summary 简洁说明结果，remaining 仅记录未完成的用户要求。
