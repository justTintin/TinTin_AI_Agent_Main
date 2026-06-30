from pymongo import MongoClient
import configparser
import sys

config = configparser.ConfigParser()
config.read('config.ini', encoding='utf-8')
path_config = config['Path']

def check_db(host, name):
    print(f"Checking MongoDB at {host}...")
    try:
        if path_config.get('Mongo_username') and path_config.get('Mongo_password'):
            client = MongoClient(host=host, port=int(path_config['Mongo_port']), 
                               username=path_config['Mongo_username'], password=path_config['Mongo_password'], 
                               authSource='admin', authMechanism='SCRAM-SHA-256',
                               serverSelectionTimeoutMS=2000)
        else:
            client = MongoClient(host=host, port=int(path_config['Mongo_port']),
                               serverSelectionTimeoutMS=2000)
        
        db_names = client.list_database_names()
        print(f"Databases found at {name}: {db_names}")
        if 'handling_vedio' in db_names:
            count = client['handling_vedio']['vedios'].count_documents({})
            print(f"Total documents in handling_vedio.vedios at {name}: {count}")
        else:
            print(f"Database 'handling_vedio' not found at {name}")
    except Exception as e:
        print(f"Could not connect to MongoDB at {name} ({host}): {e}")

check_db('127.0.0.1', 'Localhost')
check_db(path_config['Mongo_host_server'], 'Config Server Host')
