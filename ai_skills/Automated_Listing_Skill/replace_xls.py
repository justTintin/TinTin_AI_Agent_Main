import os

def replace_in_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # We only want to enforce .xlsx and remove .xls references.
    content = content.replace('("sku.xls", "sku.xlsx")', '("sku.xlsx",)')
    content = content.replace('"sku.xls"', '"sku.xlsx"')
    content = content.replace("'sku.xls'", "'sku.xlsx'")
    content = content.replace('sku.xls', 'sku.xlsx')
    content = content.replace('sku.xlsxx', 'sku.xlsx')
    
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

for root, _, files in os.walk('Automated_Listing_Skill'):
    for file in files:
        if file.endswith('.py') and file != 'replace_xls.py':
            replace_in_file(os.path.join(root, file))
