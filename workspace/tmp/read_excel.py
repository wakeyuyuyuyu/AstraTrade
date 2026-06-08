import pandas as pd
xl = pd.ExcelFile('logs/mx_data/output/mx_data_三花智控_太极实业_火炬电子_最新价_涨跌幅.xlsx')
for s in xl.sheet_names:
    print('===', s, '===')
    print(pd.read_excel(xl, s).to_string())
    print()
