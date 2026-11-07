# 船舶分段制造有限多源母材联合分配：发布候选包

英文 `README.md` 为仓库主说明。本文件提供对应的中文操作说明，不构成另一套实验口径。

**当前状态：已按作者要求上传并核验私有 GitHub 仓库，尚未向公众开放。公开前仍需作者确认工程数据共享权限、代码许可证和数据许可证，并补齐作者及论文信息。**

## 内容

- 8 个保持原始字节内容的冻结计算模块，以及新增的 CSV 读取、运行入口和独立核验程序。
- 主实例 50 个分段、4,555 件零件、2,868 根有限计划母材；受控余料池及有向材质规则。
- S0—S4 共 100 次正式运行的指标、逐根母材方案与逐件分配结果。
- 27 个标准比较案例、15 个小实例的输入及既有结果；辅助实验配置、结果和可取得的历史代码快照。
- 4 幅定量图的源数据与重绘程序、代表配对实体/零件关联表、字段字典与 SHA-256 校验清单。

这里的核心是“有限资源联合决策及其采购与资源权衡”。代表配对的 2.500 m 减少保留为可逐根核对的工程证据。

## 不重跑实验的核验

在仓库根目录执行：

```bash
python scripts/verify_release.py --report outputs/verification.json
```

核验程序只需 Python 标准库。检查 100 次主实验的 455,500 条零件分配和 194,494 根母材记录，以及实体唯一、分段隔离、材质规格、容量、采购和资源汇总。S3—S4 采购重量配对差中位数为 0.037400 t；S4 为 17 对更低、2 对持平、1 对更高。HP 160 × 10 代表配对使用同一组 35 根已有实体，均新增采购 14 根，采购长度由 135.500 m 降为 133.000 m。

绘图和导入测试的依赖单独安装：

```bash
python -m pip install -r requirements-figures.txt
python -m pip install -r requirements-solver.txt
python -m unittest discover -s tests -v
python scripts/reproduce_figures.py --output outputs/figures
```

也可使用 `conda env create -f environment.yml`。核验、单元测试和定量重绘均不调用优化求解；本次制作发布包没有新增优化实验。图 1 是方法示意，不由定量重绘脚本生成。

## 真实配置口径

S0、S1、S2 为每活动规格每阶段 500 次；**S3 单阶段为 1,000 次，S4 两阶段各为 500 次**。每阶段每规格搜索预算为 90 s，全实例共享搜索截止为 600 s；构造和合并可能在截止后完成。正式主实验关闭局部 MILP，小实例搜索则使用其单独记录的局部 MILP 配置。不得把所有正式场景写成“每阶段均为 500 次”。

## 运行入口

```bash
python scripts/run_experiment.py --family main --scenario S4 --seed 1
python scripts/run_experiment.py --family standard --case STD001 --algorithm ALNS --seed 1
python scripts/run_experiment.py --family small --case SMALL001 --algorithm EXACT --seed 1
```

以上只加载输入并展示参数。只有显式增加 `--execute` 才会开始新的求解，输出写入新的 `outputs/runs/` 子目录，不覆盖历史结果。新增适配器与原冻结算法分别标识；时间受限随机算法的跨环境重新运行不承诺与原记录逐字节一致。请从源码目录运行，不作为独立 wheel 安装。

## 公开边界

原始数据库、原始身份对应表、业务来源字段、私人准备脚本、系统日志、密钥及图像服务配置均不放入仓库。替换直接标识符，保留用于研究核验的长度、材质、规格、重量、种子和既有结果。这属于去标识化，不保证无法通过工程属性组合推断来源。

完整覆盖范围、字段解释及公开前清单分别见 `docs/COVERAGE.md`、`docs/DATA_DICTIONARY.md`、`docs/PUBLICATION_CHECKLIST.md`。仓库地址为 https://github.com/caramelling/finite-multisource-nesting ，目前保持私有，不代表已经向读者公开。
