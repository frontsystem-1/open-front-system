import os
from dotenv import load_dotenv
import subprocess
import datetime
import time
import MySQLdb
import nfc
import timeout_decorator
import requests, json
import nfc_reader
import asyncio
#import serch_return
import use_motor
from transitions import Machine
import csv

load_dotenv()

start_time = datetime.datetime.now()
cr = nfc_reader.MyCardReader()
#return_switch = serch_return.SerchReturn()
print(cr.card_type)


import requests, json

#db接続
try:
        connection = MySQLdb.connect(
        host='172.18.0.2',
        user='root',
        password='mypassword',
        db='exit_entrance_management',
        charset='utf8',
        )
        cursor = connection.cursor()
        cursor.execute('set global wait_timeout=86400')
except Exception as e:
        error_ms = str(e)
        print('error: ',error_ms)
        subprocess.call(['sudo','systemctl','restart','start_app.service'])



states = ['go', 'return','go_record','return_record','post_go_record','post_return_record']
transitions = [
	{'trigger':'go','source':'go', 'dest':'go_record'},#goの信号を受け取る
	{'trigger':'go_record','source':'go_record','dest':'post_go_record','after':'add_door_record'},#受け取った信号を登録する
	{'trigger':'return','source':'return','dest':'return_record'},#returnの信号を受け取る
	{'trigger':'return_record','source':'return_record','dest':'post_return_record','after':'add_door_record'},#returnの信号を受け取り、updateかpostかを識別し登録する
]

class SwitchDB(object):
	def __init__(self):
	    #self.page_value = input('go or return')
	    self.now = datetime.datetime.now()
	    self.day = str(self.now)[0:11]
	    self.page_value = cr.card_type #nfc_reader.pyの方で設定した入館か帰館かを反映させる
	    self.idm = '' #スキャンしたカードのid
	    #self.backup = []
	    
	#日時、名前、詳細をslackに通知させる
	def notification(day,time,name,nb):
	    if cr.error_judgment == 'error':
		    print('network error')
		    return
	    open_type = ''
	    if cr.card_type == 'go':
		    open_type = '外出'
	    elif cr.card_type == 'return':
		    open_type = '帰館'
	    url = "https://slack.com/api/chat.postMessage"
	    data = {
	    "token":'slack トークン',
	    "channel":"exitresident",
	    "text":"%s %s %s様(%s): %s" % (day,time,name,nb,open_type)
	    }
	    requests.post(url,data=data)
	#指定したidの入居者を一人抽出する
	def select_resident(resident_id):
	    cursor.execute('SELECT * FROM resident WHERE id = %s' % (resident_id))
	    return cursor.fetchone()
	    
	#idを選択し、card_recordとresidentを合わせて一致する最新のデータを1つ呼び出す
	def select_card_record(self,day,cr):
	    print('cr.idm_data' + cr.idm_data)
	    print(day + '%')
	    print('cr.card_type' + cr.card_type)
	    print('2024-01-25 check: ',cr.scan_card_name)
	    cursor.execute("""SELECT
				 resident.going_to_alone,
				 card_record.datetime,
				 card_record.type,
				 card_record.idm
				 FROM 
				 resident 
				 INNER JOIN 
				 card_record 
				 ON
				 resident.name = card_record.idm
				 WHERE
        　resident.name = '%s'
        　AND
				 resident.going_to_alone like '%s'
				 AND
				 card_record.datetime like '%s'
				 AND
				 card_record.type = '%s'
				 ORDER BY card_record.datetime DESC
			    """ % (cr.scan_card_name,'一人外出可%',day + '%',cr.card_type))
	    card_record = cursor.fetchone()
	    print('card_record: ',card_record)
	    return card_record
	    
	#日付とresident_idが一致するdoor_recordの最新のデータを一つ呼び出す
	def select_door_record(day,resident_id):
	    
	    cursor.execute("""SELECT
		    resident_id,
		    exit_day,
		    exit_time,
		    entrance_day,
		    entrance_time,
		    nb
		    FROM
		    door_record 
		    WHERE 
		    exit_day = '%s' and resident_id = %s ORDER BY exit_time DESC
		    """ % (day,resident_id)
		    )
	    return cursor.fetchone()
	
	##goかreturnかの信号を受け取り、door_recordを登録する
	def add_door_record(event):
	    check_time = event.kwargs.get('check_time')
	    resident_id = event.kwargs.get('resident_id')
	    resident_name = event.kwargs.get('resident_name')
	    resident_nb = event.kwargs.get('resident_nb')
	    page_value = event.kwargs.get('page_value')
	    day = event.kwargs.get('day')
	    time = event.kwargs.get('time')	    
	    door_state = ['exit_day','exit_time']
	    judgment = event.kwargs.get('judgment')
	    print('page_value: ' + page_value)
	    if page_value == 'return':
		    door_state = ['entrance_day','entrance_time']
		    day_record = SwitchDB.select_door_record(day,resident_id)
		    print(day_record)
		    if day_record is not None and day_record[3] is None:
			    print('return update')
			    cursor.execute(f"""update door_record set
			    entrance_day='%s',entrance_time='%s',nb='%s' 
			    where exit_day = '%s' and exit_time <= '%s' and resident_name = '%s' order by exit_time desc limit 1""" 
			    % (day,time,resident_nb,day,time,resident_name))
			    connection.commit()
			    return
	    print('puls add')
	    cursor.execute(f"""insert into
	    door_record (resident_id,%s,%s,nb,error_judgment,resident_name) 
	    values (%s,'%s','%s','%s','%s','%s')""" 
	    % (door_state[0],door_state[1],resident_id,day,time,resident_nb,judgment,resident_name))
	    connection.commit()
	    print(time)
	    SwitchDB.notification(day,time,resident_name,resident_nb) 
	
        #db_use.pyのメイン
	def mb(self,judgment):
	    
	    try:
		    asyncio.run(cr.main()) #非同期でカードリーダのpythonを起動する
		    cr.error_judgment = judgment
		    now = datetime.datetime.now()
		    day = str(now)[0:10]
		    self.idm = cr.idm_data #スキャンしたカードリーダーのidを格納する
		    print(cr.card_type) #goかreturnか出力
		    new_record = self.select_card_record(day,cr) #日付とカードの情報で一致するデータを探す
		    print('new_record + serch_return')
		    print(new_record)
		    print(cr.resident_id)
		    print(cr.scan_card_name)
		    #print(return_switch.serch_return)
		    cursor.execute("SELECT id FROM resident WHERE name = '%s'" % (cr.scan_card_name))
		    select_resident_id = cursor.fetchone() #名前で一致した入居者のid
		    print('residentname db:', select_resident_id)
		    print(new_record is not None and cr.motor_run == 'ok' and  '一人外出可能' in new_record[0])
		    if new_record is not None and cr.motor_run == 'ok' and  '一人外出可能' in new_record[0]: 
                    #日付とカードに一致したデータがあり、そのデータが一人外出可能と、motor_runがokの場合
			    machine = Machine(model=SwitchDB, states=states, transitions=transitions, initial=self.page_value,
			    auto_transitions=False, ordered_transitions=False,send_event=True)
                            #machineにtransitionに必要なのデータを入れる
			    SwitchDB.trigger(self.page_value) #最初はnfc_readerで設定してあるgoかreturnが入る
			    SwitchDB.trigger(self.state,check_time=new_record[1],resident_id=select_resident_id[0],
			    resident_name=cr.scan_card_name,resident_nb=new_record[0],page_value=self.page_value,
			    day=str(new_record[1])[0:11],time=str(new_record[1])[11:19],judgment=judgment) #add_door_record()を発火する
			    print('error: ' + cr.error_judgment)
					    
	    except MySQLdb.OperationalError as e:
		    print(e)

switch_db = SwitchDB()

while True:
    try:
	    print('try')
	    print('error notified:')
	    switch_db.mb('no')
    except requests.exceptions.ConnectionError as e:
	    print(e)
	    switch_db.mb('error')

print('db end')
nfc_reader.error_push('app end')
print('end db')
