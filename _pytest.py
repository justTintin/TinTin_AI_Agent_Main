import os
test_file = r'D:\code\TinTin_AI_Agent_Client-0713\TinTin_AI_Agent_Main\_pytest.txt'
with open(test_file, 'w', encoding='utf-8') as f:
    f.write('test123')
print('file created:', os.path.exists(test_file))
print('content:', open(test_file, 'r', encoding='utf-8').read())
