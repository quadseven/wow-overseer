import os,pymysql
c=pymysql.connect(host=os.environ.get("MYSQL_HOST","mysql"),user="root",password=os.environ["MYSQL_ROOT_PASSWORD"],database="acore_characters",cursorclass=pymysql.cursors.DictCursor).cursor()
c.execute("SHOW COLUMNS FROM overseer_snapshot"); print([r['Field'] for r in c.fetchall()])
c.execute("SELECT * FROM overseer_snapshot WHERE name='Brug'"); r=c.fetchone(); print({k:r[k] for k in r if 'pos' in k or k in ('map_id','in_combat','zone_id','area_id')})
