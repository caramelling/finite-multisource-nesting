# 船舶分段制造有限多源母材联合分配：研究发布包

[English](README.md) | **简体中文**

本仓库发布有限计划球扁钢母材、受控余料与新增采购联合静态分配的研究代码和数据，考虑分段隔离及有向材质兼容约束。英文 README 为默认说明页，中英文版本采用相同的实验数据与配置口径。

仓库地址：https://github.com/caramelling/finite-multisource-nesting

**当前状态：仓库已公开，已核验无需登录即可访问。仓库所有者已确认公开并授权：代码与仓库文档采用 MIT，`data/` 中的科研数据采用 CC BY 4.0。完整条款与目录范围见 `LICENSE`、`LICENSE-DATA`、`LICENSING.md`。**

对应稿件题目为 *Joint allocation and procurement of finite multi-source bulb-flat stock for ship block manufacturing*，拟投 Ocean Engineering，尚无正式出版 DOI。作者依次为吴尚灵、李金楷、黄成涛、王权、宋德颖、衣正尧。仓库由账号 `caramelling` 维护，英文署名见[引用信息](CITATION.md)。

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

### 可选依赖

核验环境使用 Python 3.12.13。绘图和导入测试的依赖单独安装：

```bash
python -m pip install -r requirements-figures.txt
python -m pip install -r requirements-solver.txt
python -m unittest discover -s tests -v
python scripts/reproduce_figures.py --output outputs/figures
```

也可使用 `conda env create -f environment.yml`。核验、单元测试和定量重绘均不调用优化求解；本次制作发布包没有新增优化实验。图 1 是方法示意，不由定量重绘脚本生成。

## 可复现统计重分析

本仓库包含现稿实际采用的统计流程与记录结果：100,000 次配对 bootstrap、明确的随机种子，以及按归一化零差和并列秩处理的精确符号秩检验。历史 10,000 次重采样结果单独保留以便追溯，无需重跑优化实验。公开状态与文件位置记录于 `metadata/statistical_reanalysis_status.json`。

独立统计流程使用既有结果，不运行套料优化：

```bash
python -m pip install -r requirements-statistics.txt
python scripts/reproduce_statistics.py --output outputs/statistics
```

设置、来源哈希、零差及并列秩处理、新旧结果关系见[统计说明](docs/STATISTICAL_REANALYSIS_zh.md)。新结果位于`data/results/reanalysis_20261108/`，历史表不覆盖。另行进行的[原统计源码复核](docs/ORIGINAL_STATISTICS_CROSSCHECK_zh.md)已完成，历史产物与配对来源一致，regret的p值差异已定位为浮点并列秩分裂。论文继续采用设置明确的新重分析，不静默更换历史参数。

## 真实配置口径

| 场景 | 输入余料 | 有向材质代用 | 搜索阶段 | 每活动规格每阶段迭代次数 |
|---|---|---|---|---:|
| S0 | 无 | 无 | 单阶段 | 500 |
| S1 | HIGH 池 | 无 | 单阶段 | 500 |
| S2 | 无 | 有 | 固定映射 | 500 |
| S3 | HIGH 池 | 有 | 固定映射 | **1,000** |
| S4 | HIGH 池 | 有 | 固定映射后联合重分配 | **各 500** |

每阶段每规格搜索预算为 90 s，全实例共享搜索截止为 600 s；构造和合并可能在截止后完成，因此 600 s 是共享搜索截止，并非完整运行耗时的上限。正式主实验关闭局部 MILP，小实例搜索采用其单独记录的局部 MILP 配置。

## 运行入口

```bash
python scripts/run_experiment.py --family main --scenario S4 --seed 1
python scripts/run_experiment.py --family standard --case STD001 --algorithm ALNS --seed 1
python scripts/run_experiment.py --family small --case SMALL001 --algorithm EXACT --seed 1
```

以上命令只加载输入并展示参数。只有显式增加 `--execute` 才会开始新的求解，输出写入新的 `outputs/runs/` 子目录，不覆盖历史结果。制作发布包时未执行这些优化运行。CSV 适配器是新增发布工具，8 个选定的冻结计算模块保持原样。仓库提供输入、配置与既有结果的核验；受时间预算约束的随机算法在不同硬件环境下重新运行，可能产生不同的结果。运行不依赖原数据库应用。请从源码检出目录运行，不作为独立 wheel 安装。

## 目录结构

```text
configs/                  移除身份字段后的归档配置
data/inputs/              去标识化输入、案例索引、规则与资源池
data/results/             正式分配方案、既有指标与辅助实验记录
data/figure_source/       定量图使用的源数据表
src/                      选定的冻结模块及新增 CSV、核验适配器
archived_code/            可取得的历史计算模块快照
scripts/                  核验、绘图与显式启用的求解入口
tests/                    模块导入、输入加载与核验测试
metadata/                 来源信息、字段与文件清单、SHA-256 校验清单
docs/                     数据字典、覆盖范围、去标识化与发布检查说明
```

## 公开边界

原始数据库、原始身份对应表、业务来源字段、私人准备脚本、系统日志、密钥及图像服务配置均不放入仓库。替换直接标识符，保留用于研究核验的长度、材质、规格、重量、种子和既有结果。这属于去标识化，不保证无法通过工程属性组合推断来源。

作者已确认保留的科研属性可以公开。证据覆盖范围、未保留的历史运行入口和统计重建细节见 `docs/COVERAGE.md`，字段解释见 `docs/DATA_DICTIONARY.md`。稿件元数据、引用指引与投稿核对清单见 `CITATION.md` 和 `docs/PUBLICATION_CHECKLIST.md`。
