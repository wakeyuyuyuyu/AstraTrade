import sys
sys.path.insert(0, 'skills/mx-data')
from main import query_stock
import json

# 查询存储芯片相关标的 - 澜起科技(688008)
result = query_stock('688008')
print(json.dumps(result, ensure_ascii=False))
