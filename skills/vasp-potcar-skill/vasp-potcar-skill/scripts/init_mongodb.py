"""MongoDB数据库初始化脚本"""

from pymongo import MongoClient
import os

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.environ.get("MONGO_DB", "vasp_structures")


def init_database():
    """初始化MongoDB数据库和集合"""
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB]

    # 创建calculations集合
    if "calculations" not in db.list_collection_names():
        db.create_collection("calculations")

    calculations = db["calculations"]

    # 创建索引
    calculations.create_index("formula")
    calculations.create_index("space_group")
    calculations.create_index("elements")

    print(f"数据库 {MONGO_DB} 初始化完成")

    # 插入示例数据
    sample_data = [
        {
            "formula": "LiFePO4",
            "space_group": "Pnma",
            "elements": ["Li", "Fe", "P", "O"],
            "potcar_config": {
                "Li": "Li_sv",
                "Fe": "Fe_pv",
                "P": "P",
                "O": "O"
            },
            "functional": "PBE",
            "encut": 520,
            "source": "Materials Project",
            "notes": "锂离子电池正极材料"
        },
        {
            "formula": "TiO2",
            "space_group": "P42/mnm",
            "elements": ["Ti", "O"],
            "potcar_config": {
                "Ti": "Ti_pv",
                "O": "O"
            },
            "functional": "PBE",
            "encut": 520,
            "source": "Materials Project",
            "notes": "金红石型二氧化钛"
        },
        {
            "formula": "Fe2O3",
            "space_group": "R-3c",
            "elements": ["Fe", "O"],
            "potcar_config": {
                "Fe": "Fe_pv",
                "O": "O"
            },
            "functional": "PBE",
            "encut": 520,
            "source": "Materials Project",
            "notes": "赤铁矿"
        },
        {
            "formula": "NiO",
            "space_group": "Fm-3m",
            "elements": ["Ni", "O"],
            "potcar_config": {
                "Ni": "Ni_pv",
                "O": "O"
            },
            "functional": "PBE",
            "encut": 520,
            "source": "user_calculation",
            "notes": "氧化镍，反铁磁绝缘体"
        }
    ]

    # 检查是否已有数据
    if calculations.count_documents({}) == 0:
        calculations.insert_many(sample_data)
        print(f"已插入 {len(sample_data)} 条示例数据")
    else:
        print("数据库已有数据，跳过示例数据插入")

    client.close()


if __name__ == "__main__":
    init_database()
