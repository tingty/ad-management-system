# 可复现回归测试

V4.44 / N06：把「文档里写断言通过」改成仓库里可直接运行的测试。

## 运行

```bash
python3 tests/run_all.py
# 或单个模块
python3 -m unittest discover -s tests -p test_claims.py -v
```

仅依赖 Python 标准库（`unittest`），不需要 pytest、数据库服务或网络。
`tests/_bootstrap.py` 在任何后端模块导入之前把 `DATABASE_URL` 指向临时目录，
并强制清空 `DEFAULT_LLM_API_KEY` / `DEFAULT_LLM_BASE_URL`，
因此不会读取 `.env` 里的真实密钥、不会发起付费模型调用、不会改动生产数据。

## 覆盖范围

| 文件 | 对应缺口 / 用例 | 主要断言 |
| --- | --- | --- |
| `test_claims.py` | N01 / A06 / A07 | `[E###]` 单一命名空间、原文可定位、无效编号拒绝、短句丢限定阻断、生成后审计 |
| `test_scene_policy.py` | N02 / A03 / A09 | 声明式场景策略、无哈希动作池、软件真实 UI 不被 no-UI 删除、claim 绑定证据快照 |
| `test_placement_rules.py` | N04 / A10 / A11 | 版位 + 尺寸 + 角色完整主键、未知版位拒绝、Moloco 目录、未核验标记 |
| `test_jobs.py` | N05 / A16 / A18 / A19 | 子任务预登记、幂等作用域隔离、同键异内容冲突、重启分类恢复、分项重试 |
| `test_security.py` | N06 | 源码无固定口令与自愈重置、引导文件被忽略、显式轮换入口存在 |
| `test_auto_creation.py` | V4.45 / A01–A08 / A10 / A13 / A15 / N03 | 确定性策划契约、60–120 字推荐描述、跨行业主体场景、阻断项、限定词与价格门、草案交付门、计划版本失效 |
| `frontend/auto_creation_session.mjs` | V4.45 / A01 / A02 / A13 / D3 | 经 esbuild 打包后由 node 真实执行 `creationSession.ts`：默认 auto、旧 v2 会话迁移 custom、storage key 稳定、模式切换不丢数据、计划版本失效 |

前端会话用例需要本机 `node` 与已安装的本地 esbuild；缺失时该用例自动跳过，不影响其余纯 Python 回归。

## 四种状态必须分开写

按验收文档要求，任何交付报告都只能写实际做到的状态：

| 状态 | 本目录能提供什么 |
| --- | --- |
| 代码已实现 | 由对应测试模块的源码扫描 / 结构断言覆盖 |
| 模拟测试通过 | 本目录全部用例（纯函数、临时 SQLite、模拟对象） |
| 真实模型验证 | **不覆盖**，须另附真实模型样本与输出 |
| 真实投放验证 | **不覆盖**，须另附受控实验与 CTR / CPA / ROAS 数据 |

测试通过不等于素材视觉合格，更不等于投放效果提升。
