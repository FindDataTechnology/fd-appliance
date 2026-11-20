# fd-appliance — 行业线整机交付包构建器

把一条行业线（跨境电商 / ERP / 连锁餐饮 / 供应链）打成一个可以装进客户机房的交付包：
代码、数据、依赖、校验清单一起走，客户那边断网也能跑起来。

领域无关——它不知道"跨境电商"是什么，只知道怎么把一个 `Manifest` 里的组件凑成
一个自校验的包。四类行业的具体组件清单由调用方提供（见 `tenants/`）。

## 四条不变量

这是本仓存在的理由。任何一条被破坏，交付出去的包就不该用：

```
1. 可私有化    构建期拦公网硬依赖与云端专属组件      guard.py
2. 数据三档    随包 / 在线增量 / 客户自采，逐源声明   tiers.py
               （未声明 = 不出包，不是"默认随包"）
3. 版本化增量  基座 + 增量 == 目标全量               incremental.py
4. 断网可用    包自校验 + provenance 全验             verify.py
```

第 2 条容易被误解：它检查的是**每个数据源都必须显式声明档位**，不是"没声明就当随包"。
少写一行，那个源的数据就静默缺席——所以缺声明直接拒绝构建。

## 怎么用

```bash
pip install -e .
python -m appliance_packer --help
```

构建一个包的最小路径：

```python
from appliance_packer import Manifest, verify_pack_dir

manifest = Manifest.load("tenants/<vertical>/manifest.yaml")
# ...见 demo/offline_stack.py 的完整流程
report = verify_pack_dir("<pack-dir>")
assert report.ok
```

## 目录

| 路径 | 是什么 |
|---|---|
| `appliance_packer/` | 构建器本体（上面四条不变量 + 打包/校验入口） |
| `tenants/` | 四条行业线的组件清单：`crossborder` `erp` `restaurant-chain` `supply-chain` |
| `demo/offline_stack.py` | 端到端演示：从 manifest 到断网可跑的栈 |
| `ci/` `tests/` | 构建守卫与不变量的测试 |

## 规格

四条不变量的完整定义与场景在 `openspec/changes/add-crossborder-appliance-pack`。
本 README 只给能上手的最小信息；判据以那份 spec 为准。

## License

MIT — 见 `LICENSE`。
