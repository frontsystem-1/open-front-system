import os
import sys
import subprocess
from flask import Flask, request, render_template, jsonify, redirect, url_for
from flask_paginate import Pagination, get_page_parameter
import datetime
import time
import nfc
import requests
import MySQLdb
from flask_bcrypt import Bcrypt
import asyncio
import nfc_reader
from transitions import Machine

import psutil
from itertools import chain

app = Flask(__name__)
bcrypt = Bcrypt()

cr = nfc_reader.MyCardReader()
print(cr.card_type)


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
    print('apache Trueexit')
    cursor.execute('set global wait_timeout=86400')
except Exception as e:
    print('apache False')
    error_ms = str(e)
    print('error: ',error_ms)
    time.sleep(5)
    subprocess.call(['sudo','systemctl','restart','start_app.service'])

states = ['go', 'return','go_record','return_record','post_go_record','post_return_record']

transitions = [
	{'trigger': 'go','source':['go', 'return'], 'dest': 'go_record'}, #goの信号を受け取る
	{'trigger':'go_record','source':'go_record', 'dest':'post_go_record','after':'insert_door'}, #受け取った信号を登録する
	{'trigger': 'post_go_record', 'source':'post_go_record', 'dest': 'go'},
	{'trigger': 'return','source': ['return', 'go'], 'dest':'return_record'}, #returnの信号を受け取る
	{'trigger':'return_record','source':'return_record', 'dest':'post_return_record','after':'insert_door'}, #returnの信号を受け取り、updateかpostかを識別し登録する
	{'trigger': 'post_return_record', 'source':'post_return_record', 'dest': 'return'}
	]


auth_array = []
post_data = []


class SwitchView(object):
	def __init__(self):
	    self.url_after_create = '' #/createで使用。フロントシステムでは使用しない
	    self.url_after_update = 'no_url' #/updateで使用。フロントシステムでは使用しない
	    self.login_staff = 'no staff' #ログインしているstaffのidを格納
	#全てのstaffのデータを取得し、その中に選択したidがあったらTrueを返す
	def all_staff_id(staff_id):
	    cursor.execute('SELECT id FROM staff')
	    all_staff = tuple(item[0] for item in (cursor.fetchall()))
	    if int(staff_id) in all_staff:
		    return True
	#引数のstaffのidのデータをstaffテーブルから一つだけ取り出す
	def serch_staff(staff_id):
	    cursor.execute('SELECT * FROM staff WHERE id = %s' % (staff_id))
	    serch_staff_data = cursor.fetchone()
	    return serch_staff_data

	def login_staff(login_id):
	    cursor.execute('''
            SELECT * FROM staff
            WHERE
            login_id = '%s'
            ''' % (login_id))
	    auth_staff = cursor.fetchone()
	    return auth_staff
	#サインイン画面の処理
	@app.route('/sign_in', methods=['GET','POST'])
	def sign_in():
	    try:
		    now = datetime.datetime.now()
		    day = str(now)[0:11]
		    #SwitchView.login_staff = 'no staff'
		    home_url = 'no url'
		    if request.method == 'POST':
			    #送られてきたidと一致するstaffデータを取得し、auth_staffに格納
			    login_id = request.form['login_id']
			    password = request.form['password']
			    print(login_id)
			    print(password)
			    hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
			    auth_staff = SwitchView.login_staff(login_id)
			    print('auth_staff: ',auth_staff)
			    #auth_staffがからなら/sign_inに飛ぶ
			    if auth_staff is None:
				    return render_template('sign_in.html')
			    #auth_staffがNoneでなく、かつ送られてきたパスワードと登録されているパスワード(ハッシュ化を解いた状態)が一致するか
			    elif bcrypt.check_password_hash(auth_staff[3],password):
				    print('login')
				    home_url = request.host_url  + '/' + day + '/-1/all_record'
				    login_staff = auth_staff
				    print('staff_id')
				    print(auth_staff[0])
				    auth_array.append(auth_staff[0])
				    post_data.append('更新')
				    print('sign in auth_array')
				    print(auth_array)
				    return redirect(url_for('home_view',staff_id=auth_staff[0]))
			    else:
				    print('no staff')
				    home_url = 'no url'
				    return render_template('sign_in.html')
	    except MySQLdb.OperationalError as e:
		    print(e)
	    return render_template('sign_in.html')
			    
	def add_staff_card(last_name,name,idm_data):
	    cursor.execute('''
	    INSERT INTO staff_card(name,card_id)
	    VALUE('%s','%s')
            ''' % ((last_name + '　' + name),idm_data))
	    connection.commit()
	#職員登録ページの処理
	@app.route('/<int:staff_id>/sign_up', methods=['GET','POST'])
	def sign_up(staff_id):
	    try:
		    message = ''
		    login_staff = SwitchView.serch_staff(staff_id) #login_staffのを引数のstaff_idを使って獲得する
		    if auth_array == [] and request.method == 'GET': #誰もログインしていない状態であれば/sign_inに飛ぶ
			    return redirect(url_for('sign_in'))
		    elif auth_array == []:
			    auth_array.append(staff_id)
		    elif staff_id not in auth_array:
			    return redirect(url_for('sign_in'))
		    if SwitchView.all_staff_id(staff_id) and request.method == 'POST': #引数のstaff_idがデータベースのstaff内にあり、かつ、登録するデータが送られてきている場合
			    name = request.form['name'] 
			    last_name = request.form['last_name'] 
			    kill_db_use() 
			    #裏で動いている扉開閉用のカードリーダーシステムを一度止める
			    print(cr.idm_data) 
			    restart_db_use() 
			    #再び扉開閉用のカードリーダーシステムを再開する 
			    SwitchView.add_staff_card(last_name,name,cr.idm_data) 
			    message = '職員データを登録できました。'
	    except UnboundLocalError:
		    login_staff = SwitchView.serch_staff(staff_id)
	    except MySQLdb.OperationalError as e:
		    print(e)
	    return render_template('sign_up.html',staff_id=staff_id,login_staff=login_staff,message=message)
	
	#residentの文字列をidとgoing_to_aloneに分ける。indexページで送られてくる入居者データは、idとgoing_to_aloneを繋げて一つの文字列として送ってくる(引数のresident)。
	def select_resident_nb_value(resident):
	    resident_value = []
	    while resident_value == []:
		    #それぞれを配列として[id,going_to_alone]に分ける
		    if resident.endswith('出可能'):
			    resident_value = [resident[:-6],resident[-6:]]
		    elif resident.endswith(')'):
			    resident_value = [resident[:-10],resident[-10:]]
		    elif resident.endswith('不可能'):
			    resident_value = [resident[:-7],resident[-7:]]
		    if resident_value == []:
			    continue
	    return resident_value
	#全ての名前がNoneでない入居者のデータを獲得する
	def all_residents():
	    cursor.execute("SELECT * FROM resident WHERE name != 'None' ORDER BY number ASC")
	    return cursor.fetchall()

	#residentから一人外出可能な人だけを取り出す
	def residents_value():
	    cursor.execute("""SELECT
			*
			FROM
			resident
			WHERE 
			reason = 'exist'
			AND
			name != 'None'
			ORDER BY number ASC
			""")
	    residents = cursor.fetchall()
	    return residents
	
	#日付を選択し、その日の記録を取り出す
	def today_value(day):
	    cursor.execute("""SELECT
			    resident.name,
			    exit_day,
			    exit_time,
			    entrance_day,
			    entrance_time,
			    nb
			    FROM
			    door_record
			    INNER JOIN
			    resident
			    ON
			    door_record.resident_name = resident.name
			    WHERE 
			    exit_day = '%s' OR entrance_day = '%s' ORDER BY exit_time DESC
			    """% (day,day))
	    today = cursor.fetchall()
	    return today
	def select_name(resident_id):
	    cursor.execute('SELECT name FROM resident where id = %s' % (resident_id))
	    resident_data = cursor.fetchone()
	    return resident_data

	#すべてのdoor_recordか、entrance_dayにデータが入っている物のみか、entrance_dayがNullの物かを選択し、呼び出す
	def serch_today_value(day,resident_id,return_check):
	    print('resident_id: ',resident_id)
	    select_value = 1
	    resident_name = '-1'
	    day_format = datetime.datetime.strptime(day, '%Y-%m-%d')
	    new_day = day_format + datetime.timedelta(days=1)
	    tomorrow = new_day.strftime('%Y-%m-%d')
	    if int(resident_id) == -1:
		    select_value = 'IS NOT NULL'
	    if int(resident_id) != -1:
		    resident_data = SwitchView.select_name(resident_id)
		    resident_name = resident_data[0]
		    select_value = "= " +  str(resident_id)
	    cursor.execute("SELECT * FROM card_record WHERE datetime LIKE '%s'" % (day + '%'))
	    record_check = cursor.fetchall() 
	    if record_check is None:
		    cursor.execute("""INSERT INTO card_record(datetime,type,idm) 
		    VALUES('%s','go','error block record')
		    """ % (day + ' 00:00:00'))
		    connection.commit()
	    today = ''
	    if return_check == 'all_record': #全てのデータ
		    print('1')
		    cursor.execute("""
		    SELECT r.name,
			t1.datetime,
			t1.staff_name,
			t1.reason,
			t1.update_time,
			t2.datetime,
			t2.staff_name,
			t2.reason,
			t2.update_time,
			t1.id,
			t2.id,
			t1.first_time,
			t2.first_time,
			t1.return_id,
			t2.go_id,
			t1.return_complete
			FROM resident r
			LEFT JOIN card_record t1
			ON r.name = t1.idm
			AND t1.datetime >= '%s 00:00:00'
			AND t1.datetime < '%s 00:00:00'
			LEFT JOIN return_data t2
			ON r.name = t2.idm
			AND t2.datetime >= '%s 00:00:00'
			AND t2.datetime < '%s 00:00:00'
			AND (t1.datetime <= t2.datetime OR t1.datetime = '%s 00:00:00' 
			OR t2.datetime = '%s 00:00:00')
			WHERE 
			(t1.datetime IS NOT NULL OR t2.datetime IS NOT NULL)
			AND (t1.id = t2.go_id AND t1.return_id = t2.id)
			AND r.id %s
			ORDER BY COALESCE(t1.datetime, t2.datetime) DESC
		   """  % (day,tomorrow,day,tomorrow,day,day,select_value))
		    today = cursor.fetchall()
	    elif return_check == 'no_return': #return_dataがないもの
		    print('2')
		    cursor.execute("""
		    SELECT r.name,
			t1.datetime,
			t1.staff_name,
			t1.reason,
			t1.update_time,
			t2.datetime,
			t2.staff_name,
			t2.reason,
			t2.update_time,
			t1.id,
			t2.id,
			t1.first_time,
			t2.first_time,
			t1.return_id,
			t2.go_id,
			t1.return_complete
			FROM resident r
			LEFT JOIN card_record t1
			ON r.name = t1.idm
			AND t1.datetime >= '%s 00:00:00'
			AND t1.datetime < '%s 00:00:00'
			LEFT JOIN return_data t2
			ON r.name = t2.idm
			AND t2.datetime >= '%s 00:00:00'
			AND t2.datetime < '%s 00:00:00'
			AND (t2.datetime = '%s 00:00:00'
			AND t1.return_complete = FALSE)
			WHERE 
			(t1.datetime IS NOT NULL AND t2.datetime IS NOT NULL)
			AND (t1.id = t2.go_id AND t1.return_id = t2.id)
			AND r.id %s
			ORDER BY COALESCE(t1.datetime, t2.datetime) DESC
		    """ % (day,tomorrow,day,tomorrow,day,select_value))
		    today = cursor.fetchall()
	    elif return_check == 'return': #return_dataにデータがあるもの
		    print('3')
		    cursor.execute("""
		    SELECT r.name,
			t1.datetime,
			t1.staff_name,
			t1.reason,
			t1.update_time,
			t2.datetime,
			t2.staff_name,
			t2.reason,
			t2.update_time,
			t1.id,
			t2.id,
			t1.first_time,
			t2.first_time,
			t1.return_id,
			t2.go_id,
			t1.return_complete
			FROM resident r
			LEFT JOIN card_record t1
			ON r.name = t1.idm
			AND t1.datetime >= '%s 00:00:00'
			AND t1.datetime < '%s 00:00:00'
			LEFT JOIN return_data t2
			ON r.name = t2.idm
			AND t2.datetime >= '%s 00:00:00'
			AND t2.datetime < '%s 00:00:00'
			AND (t1.datetime <= t2.datetime 
			OR t1.datetime = '%s 00:00:00'
			AND t2.datetime != '%s 00:00:00')
			OR (t2.datetime = '%s 00:00:00' 
			AND t1.return_complete = TRUE)
			WHERE
			(t1.datetime IS NOT NULL AND t2.datetime IS NOT NULL)
			AND (t1.id = t2.go_id AND t1.return_id = t2.id)
			AND r.id %s
			ORDER BY COALESCE(t1.datetime, t2.datetime) DESC
		    """ % (day,tomorrow,day,tomorrow,day,day,day,select_value))
		    today = cursor.fetchall()
	    return today

	#exitかentranceか選択し、新たにrecordを登録する
	def post_door_record(resident_id,day,time,nb,resident_name,go_out_reason,staff_name,request):
	     #最後に登録してあるreturn_dataのidを取得し、そこに+1をする
	     cursor.execute("""
	     SELECT id FROM return_data ORDER BY id DESC LIMIT 1
	     """)
	     new_return_id = int(cursor.fetchone()[0]) + 1
	     #card_recordを追加し、先ほど取得したnew_return_idをreturn_idとして登録
	     cursor.execute("""
	     INSERT INTO card_record(datetime,type,idm,staff_name,reason,first_time,return_id)
	     VALUES ('%s','%s','%s','%s','%s','%s','%s')
	     """ % (day + ' ' + time,request,resident_name,staff_name,go_out_reason,day + ' ' + time,new_return_id))
	     connection.commit()
	     #最後に追加されたIDを獲得するコード。上記のcard_recordのidを取得する
	     cursor.execute("SELECT LAST_INSERT_ID()")
	     last_insert_id = cursor.fetchone()[0]
	     #return_dataを日付+00:00:00で追加し、上記で獲得したlast_insert_idをgo_idに登録
	     cursor.execute("""
	     INSERT INTO return_data(datetime,type,idm,go_id) VALUES ('%s','return','%s','%s')
	     """ % (day,resident_name,last_insert_id))
	     connection.commit()
	     #この処理で、card_recordを追加すると同時に、00:00:00のreturn_dataを追加する。
	     #この二つはgo_idとreturn_idで結びつけられる
	     	
	#goかreturnかの信号を受け取り、door_recordを登録する
	def insert_door(event):
	    print('event',event)
	    if type(event) == list: #homeページからpostされたデータは、配列で届く
		    print('if list')
		    request = event[0]
		    page_value = event[1]
		    resident_nb = [event[4],event[2]]
		    resident_name = event[5]
		    go_out_reason = event[6]
		    staff_name = event[7]
		    print(resident_nb)
		    print(event[2])
		    door_time = event[3]
		    print(resident_nb)
		    day = 'exit_day'
		    time = 'exit_time'
		    return_value = ''
	    elif type(event) != list: #indexページからpostされたデータは、transitionsの影響で'event.kwargs.get'で呼び出す
		    print('event.kwargs.get: ',event.kwargs.get('resident_name'))
		    request = event.kwargs.get('data')
		    page_value = event.kwargs.get('page')
		    resident_nb = SwitchView.select_resident_nb_value(event.kwargs.get('resident_nb'))
		    resident_name = event.kwargs.get('resident_name')
		    door_time = event.kwargs.get('door_time')
		    go_out_reason = ''
		    staff_name = event.kwargs.get('staff_name')
		    print(resident_nb)
		    return_value = ''
		    print('staff_name: ',staff_name)
	    if request == 'return': #帰宅のリクエストの場合
		    #名前が一致し、かつdatetimeが00:00:00のreturn_dataを取得
		    cursor.execute(""" SELECT id FROM return_data WHERE idm = '%s' AND datetime = '%s'ORDER BY id DESC
		    """ % (resident_name,page_value + ' 00:00:00'))
		    return_data_id = cursor.fetchone()
		    #もし、return_dataデータがあれば
		    if return_data_id is not None:
			    print('update root')
			    #獲得したreturn_dataのidで、そのデータを更新する
			    cursor.execute("""UPDATE return_data SET datetime = '%s',staff_name = '%s',reason='%s',first_time = '%s' where id = '%s'
			    """ % (page_value + ' ' + door_time,staff_name,go_out_reason,page_value + ' ' + door_time,return_data_id[0]))
			    connection.commit()
		    #return_dataがない場合は
		    elif return_data_id is None:
			    print('else root')
			    #card_recordの最後のidを獲得
			    cursor.execute(""" SELECT id FROM card_record ORDER BY id DESC""")
			    card_record_id = cursor.fetchone()
			    #return_dataを新規作成
			    #作成したreturn_dataのgo_idを獲得したcard_record_id+1として登録
			    cursor.execute("""INSERT INTO
			    return_data(idm,datetime,type,staff_name,reason,first_time,go_id)
			    VALUES('%s','%s','return','%s','%s','%s','%s')
			    """ % (resident_name,page_value + ' ' + door_time,staff_name,go_out_reason,page_value + ' ' + door_time,int(card_record_id[0]) + 1))
			    connection.commit()
			    #先後に登録したIDを獲得
			    #この場合はreturn_dataを登録したばかりのため、return_dataのidを獲得
			    cursor.execute("SELECT LAST_INSERT_ID()")
			    last_insert_id = int(cursor.fetchone()[0])
			    #card_recordを00:00:00として新規登録
			    #return_idに先ほど獲得したlast_insert_idを登録
			    #card_recordを登録した際にreturn_dataも作成しされる
			    #そもそもreturn_dataがないという事は、一致するcard_recordもない状態
			    #そのためreturn_idの一致するcard_recordを登録する必要がある
			    cursor.execute("""INSERT INTO card_record(idm,datetime,type,return_id)
			    VALUES('%s','%s','go','%s')""" % (resident_name,page_value + ' 00:00:00',last_insert_id))
			    connection.commit()
		    #新たに登録したreturn_dataを下に、
		    #その入居者の登録した日時よりも前のcard_recordに、return_completeをTRUEにする
		    #return_completeがTRUEの場合は、retrun_dataが00:00:00でも帰宅済みとする
		    cursor.execute("""
                    UPDATE card_record SET return_complete = TRUE  WHERE idm = '%s' AND  return_complete = FALSE  AND  datetime like '%s' AND datetime < '%s'
                    """ % (resident_name,page_value + '%',page_value + ' ' + door_time))
		    connection.commit()
		    return		    
	    SwitchView.post_door_record(resident_nb[0],page_value,door_time,resident_nb[1],resident_name,go_out_reason,staff_name,request)	    
	
machine = Machine(model=SwitchView, states=states, transitions=transitions, initial='go',
				    auto_transitions=False, ordered_transitions=False,send_event=True) #transitionsに必要

#indexページ 引数でログインしているstaffと日付、選択している入居者、記録の状態を与えている
@app.route('/<int:staff_id>/<string:page_value>/<string:resident_id>/<string:return_check>', methods=['GET','POST'])
def return_view(staff_id,page_value,resident_id,return_check):
    try:
	    """
	    if auth_array == [] and request.method == 'GET':
		    return redirect(url_for('sign_in'))
	    elif auth_array == []:
		    auth_array.append(staff_id)
	    elif int(staff_id) not in auth_array:
		    return redirect(url_for('sign_in'))
	    """
	    now = datetime.datetime.now()
	    day = str(now)[0:11]
	    time = str(now)[11:19]
	    data = request.get_json()
	    today = ''
	    residents = ''
	    limit = ''
	    page = ''
	    pagination = ''
	    residents = SwitchView.residents_value() #全入居者のデータ
	    cursor.execute("""INSERT INTO card_record(datetime,type,idm) 
            VALUES('%s','go','error block record')
            """ % (day + ' 00:00:00'))
	    connection.commit()

	    method_value = request.method #postかgetか
	    select_resident_name = '-1' # 最初はは-1、-1でmysqlのwhere文を使うと全てが表示される
	    cursor.execute("select name from staff where id = '%s'" % (staff_id)) #ログインしているstaffの名前を取得しstaff_nameに与える
	    staff_name = cursor.fetchone()
	    if SwitchView.all_staff_id(staff_id) and request.method == 'POST': #ログインしているstaffが登録されており、データがpostされてきている状態の場合
		    print('data.get', data.get('go_out'),data.get('door_date'),data.get('door_time'),data.get('select_resident_id'))

		    resident_nb = SwitchView.select_resident_nb_value(data.get('select_resident_id')) #postされたデータをselect_resident_nbをidとgoing_to_aloneに分ける
		    select_resident = SwitchView.select_name(resident_nb[0])
		    select_resident_name = select_resident[0]
		    today = SwitchView.serch_today_value(page_value,resident_id,return_check) #indexページで選択したpage_value(日付)、入居者のid、記録の状態を使い、それに合った記録を呼び出す
		    if data.get('door_time') is not None and data.get('go_out') is not None:
		    # door_record が None でなく、door_time が送信されていて、かつ door_time が door_record[3] と異なる場合の処理
		    # (indexページのformでデータを送った場合)
			    SwitchView.trigger(data.get('go_out'))
			    SwitchView.trigger(SwitchView.state,data=data.get('go_out'),page=data.get('door_date'),door_time=data.get('door_time'),
			    resident_nb=data.get('select_resident_id'),resident_name=select_resident_name,staff_name=staff_name[0])
			    trigger_name = data.get('go_out') #最後transitionsはgoかreturnに戻るようにしている
			    if trigger_name == 'go': #先ほどtrigger_nameに格納したgoかreturnを,SwitchView.state (現在の状態)に代入し、go→go_out→post_go_out→go→の状態を作っていく
				    SwitchView.state = 'go'
			    elif trigger_name == 'return': #return側も上記と同様
				    SwitchView.state = 'return'
			    
		    if resident_nb != []: #postされたデータがselect_resident_nbをidとgoing_to_aloneでもなく空だった場合
			    today = SwitchView.serch_today_value(page_value,-1,return_check) #指定する引数は記録の状態のみで、他は全ての条件を含めたその日の記録を呼び出す
			    #today = card_record
	    if request.method == 'GET':
		    if page_value != 'favicon.ico':
			    day_value = page_value
			    today = SwitchView.serch_today_value(page_value,resident_id,return_check)
			    #today = card_record
	    #下記は記録のページ機能に必要な処理
	    page = request.args.get(get_page_parameter(), type=int, default=1)
	    limit = today[(page -1)*10:page*10]
	    pagination = Pagination(page=page, total=len(today))
	    login_staff = SwitchView.serch_staff(staff_id) 
	    
    except UnboundLocalError:
	    login_staff = SwitchView.serch_staff(staff_id)
    except MySQLdb.ProgrammingError as e:
	    print('ProgramingError')
	    print(e)
	    login_staff = SwitchView.serch_staff(staff_id)
	    return render_template('index.html', staff_id=staff_id,login_staff=login_staff,residents=residents, today=limit, day_value=day,
           local_time=time, pagination=pagination, page=page, page_value=page_value, resident_data=resident_id, return_check=return_check)

    except MySQLdb.OperationalError as e:
	    print(e)
	    login_staff = SwitchView.serch_staff(staff_id)
    return render_template('index.html', staff_id=staff_id,login_staff=login_staff,residents=residents, today=limit, day_value=day,
	   local_time=time, pagination=pagination, page=page, page_value=page_value, resident_data=resident_id, return_check=return_check)

@app.route('/record_update',methods=['POST']) #indexページから送られてきたデータを元に記録更新を行う
def record_update() :
    try:
	    now = datetime.datetime.now()
	    day = now.strftime("%Y-%m-%d")
	    time = now.strftime("%H:%M:%S")
	    data = request.get_json()
	    resident_name = data.get('resident_name')
	    go_id = data.get('go_id')
	    return_id = data.get('return_id')
	    go_time = data.get('go_time')
	    return_time = data.get('return_time')
	    reason = data.get('reason')
	    go_first_time = data.get('go_first_time')
	    return_first_time = data.get('return_first_time')
	    print(go_first_time,return_first_time)
	    print('go_id: ',go_id)
	    print('return_id: ',return_id)
	    if go_id != 'None':
		    cursor.execute("""
		    UPDATE card_record SET datetime = '%s',reason = '%s',update_time = '%s',first_time = '%s'
		    WHERE id = %s
		    """ % (go_time,reason,day+ ' ' + time,go_first_time,go_id))
		    connection.commit()
		    cursor.execute("SELECT first_time FROM card_record WHERE id = %s" % (go_id))
		    if cursor.fetchone() is not None:
			    cursor.execute("UPDATE card_record SET first_time = '%s' WHERE id = %s" % (go_first_time,go_id))
			    connection.commit()
	    if return_id != 'None' and go_id == 'None' and go_time != day + ' 00:00:00':
		    cursor.execute("""
                    SELECT id FROM card_record WHERE datetime = '%s' and idm = '%s' and  return_id = '%s' LIMIT 1
                    """ % (go_time,resident_name,return_id))
		    card_record_id = cursor.fetchone()
		    cursor.execute("""
                    UPDATE return_data SET datetime = '%s',reason = '%s',update_time = '%s', first_time = '%s',go_id = '%s'
                    WHERE id = %s
                    """ % (return_time,reason,day + ' ' + time,return_first_time,card_record_id[0],return_id))
	    elif return_id != 'None':
		    cursor.execute("""
		    SELECT datetime FROM return_data WHERE id = %s
		    """ % (return_id))
		    check_time = cursor.fetchone()[0]
		    if str(check_time) == day + ' 00:00:00':
				    return_first_time = return_time
		    cursor.execute("""
		    UPDATE return_data SET datetime = '%s',reason = '%s',update_time = '%s', first_time = '%s'
                    WHERE id = %s
		    """ % (return_time,reason,day + ' ' + time,return_first_time,return_id))
		    connection.commit()
		    cursor.execute("""
                    UPDATE card_record SET return_complete = TRUE  WHERE idm = '%s' AND  return_complete = FALSE  AND  datetime like '%s' AND datetime < '%s'
                    """ % (resident_name,day + '%',day + ' ' + time))
		    connection.commit()
	    elif return_id == 'None' and return_time != day + ' 00:00:00':
		    cursor.execute("""
		    INSERT INTO return_data(datetime,type,idm,reason,update_time,first_time,go_id)
		    VALUES ('%s','return','%s','%s','%s','%s','%s')
		    """ % (return_time,resident_name,reason,day + ' ' + time,return_first_time,go_id))
		    connection.commit()
		    cursor.execute("""
		    SELECT id FROM return_data WHERE datetime = '%s' and idm = '%s' and go_id = '%s'
		    """ % (return_time,resident_name,go_id))
		    return_data_id = cursor.fetchone()
		    cursor.execute("""
		    UPDATE card_record
		    SET return_id = '%s' WHERE id = %s
		    """ % (return_data_id[0],go_id))
		    connection.commit()
		    cursor.execute("""
                    UPDATE card_record SET return_complete = TRUE  WHERE idm = '%s' AND  return_complete = FALSE  AND  datetime like '%s' AND datetime < '%s'
                    """ % (resident_name,day + '%',day + ' ' + time))
		    connection.commit()
	    return jsonify({'status': 'success'})

    except ValueError:
	    print('ValueError')


#入居者を登録するフロントシステムでは/createページは使っていない
def post_resident(self,staff_id,name,number,room_number,going_to_alone,card_id):
    try:
	    if staff_id not in auth_array:
		    return redirect(url_for('sign_in'))
	    self.url_after_create = 'no url'
	    now = datetime.datetime.now()
	    day = str(now)[0:11]
	    cursor.execute("""
	    INSERT INTO 
	    resident
	    (name,number,number_people,going_to_alone,card_id) 
	    VALUES
	    ('%s',%s,%s,'%s','%s')
	    """ % (name,int(number),int(room_number),going_to_alone,card_id))
	    connection.commit()
	    self.url_after_create = request.host_url +'/' + str(staff_id) + '/' + day + '/-1/all_record' #登録後に/createからindexページに飛ぶように全体のurlデータに格納しておく
    except ValueError:
	    print('ValueError')
	    self.url_after_create = request.host_url + '/' + str(staff_id) + '/create'
    print(self.url_after_create)
#入居者のデータを更新するページ フロントシステムでは/updateページは使っていない
def post_update_resident(self,staff_id,resident_id,name,number,room_number,going_to_alone,card_id):
    try:
	    if auth_array == [] and request.method == 'GET':
		    return redirect(url_for('sign_in'))
	    elif auth_array == []:
		    auth_array.append(staff_id)
	    elif staff_id not in auth_array:
		    return redirect(url_for('sign_in'))
	    self.url_after_update = 'no url'
	    now = datetime.datetime.now()
	    day = str(now)[0:11]
	    cursor.execute("""
	    UPDATE resident
	    SET name = '%s',number = %s,number_people= %s,going_to_alone='%s',card_id='%s'
	    WHERE id = %s
	    """ % (name,int(number),int(room_number),going_to_alone,card_id,resident_id))
	    connection.commit()
	    self.url_after_update = request.host_url +'/' + str(staff_id) + '/' + day + '/-1/all_record' #登録後に/updateからindexページに飛ぶように全体のurlデータに格納しておく
    except ValueError:
	    print('ValueError')
	    self.url_after_update = request.host_url + '/' + str(staff_id) + '/update'
    print(self.url_after_update)
    
def kill_db_use():
	# 停止したいプロセス名を指定する
	process_name = "db_use.py"
	print('kill db_use')
	os.system(f'sudo pkill -f {process_name}')

#入退館用のカードリーダーを再開する
def restart_db_use():
	process_name = "/var/www/html/db_use.py"
	process = subprocess.Popen(["python3", process_name])

#/sign_outページ、ログアウト機能
@app.route('/<int:staff_id>/sign_out', methods=['GET','POST'])
def sign_out(staff_id):
    try:
	    user_agent = request.headers.get('User-Agent')
	    print(user_agent)
	    print(request.method == 'POST')
	    if request.method == 'POST':
		    print('POST')
		    data = request.get_json()
		    post_data.append(data) #ページから送られてくる信号を格納する配列
		    print('auth_array')
		    print(auth_array)
		    
		    
		    if 'ログアウト' in post_data: #layout.htmlのログアウトボタンを押すと'ログアウト'の文字列をpostするようにしている。
			    auth_array.remove(staff_id) #その際にページURLから渡されたログインユーザーをauth_array（ログインユーザーを格納している配列）から取り除く
			    post_data.clear()
		    elif auth_array.count(staff_id) >= 2: #同じユーザーが2人以上の場合片方を取り除く。そのような場合は2窓で同じユーザーでログインしている
			     auth_array.remove(staff_id)
		   
			    
		    print('auth_array')
		    print(auth_array)
		    return 'page change'
	    print('auth_array last')
	    auth_array.remove(int(staff_id))
	    print(auth_array)
    except  ValueError:
	    return redirect(url_for('sign_in'))
    return redirect(url_for('sign_in'))
	
#現在登録されている1015までの入居者データをfloor(3から10)を各階1から順に16部屋に分ける
def resident_data(floor):
	start_id = floor + '01'
	end_id = floor + '16'
	cursor.execute("""SELECT * FROM resident 
	WHERE (number BETWEEN %s AND %s)
	AND (number <= 1015)
	ORDER BY number ASC, (CASE WHEN number_people = 0 THEN 1 ELSE 2 END);
	""" % (int(start_id), int(end_id)));
	results = cursor.fetchall()
	return results
#全ての登録されている共有スペースのデータ
def all_space_name():
	cursor.execute("SELECT * FROM space_data");
	results = cursor.fetchall()
	return results

#/homeページ
@app.route('/<int:staff_id>/home',methods=['GET','POST'])
def home_view(staff_id):
	now = datetime.datetime.now()
	day = now.strftime("%Y-%m-%d")
	time = now.strftime("%H:%M:%S")
	db_check = 'check'
	print('date: ', day+ time)
	print('home page?')
	current_year = datetime.datetime.now().year
	current_month = datetime.datetime.now().month
	calendar_month = f"{current_year}-{current_month:02d}" #年月
	cursor.execute("""
                        SELECT 
                        r.name,
                        t1.datetime,
                        t2.datetime
                        FROM 
                        resident r
                        LEFT JOIN 
                        card_record t1 ON r.name = t1.idm 
                        AND t1.datetime LIKE '%s'
                        LEFT JOIN 
                        return_data t2 ON r.name = t2.idm 
                        AND t2.datetime LIKE '%s'
                        AND (t1.datetime <= t2.datetime OR t1.datetime is NULL)
                        WHERE 
                        (t1.datetime IS NOT NULL 
                        AND t2.datetime IS NULL )  
                        ORDER BY 
                        t1.datetime DESC
	""" % (day + '%',day + '%'))
	#go_resident = list(chain(*cursor.fetchall()))
	go_resident = list(chain(*cursor.fetchall()))
	cursor.execute("SELECT start_time FROM space_rental") #レンタルされている共有スペースの開始時間を獲得し、check_spaceに格納する
	check_space = cursor.fetchall()
	space_rental_all = ''
	all_data = []
	for i in range(3, 11): #301から1015までの入居者のデータを階毎に配列に格納していく
		data = resident_data(str(i))
		all_data.append(data)
	all_space = all_space_name() #全ての共有スペースのデータをall_spaceに格納する
	cursor.execute("SELECT * FROM staff") #全てのstaffのデータをstaff_dataに格納する
	staff_data = cursor.fetchall()
	login_staff = SwitchView.serch_staff(staff_id)
	cursor.execute("""
	SELECT space_name,start_time,end_time FROM space_rental
	WHERE start_time >= '%s' OR end_time >= '%s'
	""" % (day + ' ' + time[:-3],day + ' ' + time[:-3]))
	print('start_time: ',day + ' ' + time[:-3]) #共有スペースをレンタルする際に被ってないか確認するために、現在時間よりも後に登録されているレンタルスペースデータをsdb_checkに格納
	db_check=cursor.fetchall()
	cursor.execute("SELECT * FROM remarks") #備考テンプレートを取得しremarksに格納
	remarks = cursor.fetchall()
	return render_template('home.html',staff_id=staff_id,login_staff=login_staff, all_data=all_data,space_data='',space_name='',
	all_space=all_space,day='',staff_data=staff_data,space_rental_all=space_rental_all,select_month='',go_resident=go_resident,
	space_check='',db_check=db_check,remarks=remarks)
#/settingページ
@app.route('/<int:staff_id>/setting')
def setting_view(staff_id):
        all_data = []
        #部屋移動時に選択する用の入居者データをmove_residentに格納
        cursor.execute("SELECT id,name,number,number_people,going_to_alone FROM resident WHERE number BETWEEN 301 AND 1015 ORDER BY number,number_people ASC;")
        move_resident = cursor.fetchall()
        cursor.execute("SELECT * FROM staff")
        staff_data = cursor.fetchall()
        login_staff = SwitchView.serch_staff(staff_id)
        space_data = all_space_name() #全ての共有スペースのデータ
        for i in range(3, 11):
                data = resident_data(str(i))
                all_data.append(data)
        all_space = all_space_name() #入居者の部屋データ
        cursor.execute("SELECT * FROM remarks")
        remarks = cursor.fetchall()
        return render_template('setting.html',staff_id=staff_id,login_staff=login_staff, all_data=all_data,space_data=space_data,space_name='',
        all_space=space_data,day='',staff_data=staff_data,move_resident=move_resident,remarks=remarks)
#settingページで行われる処理
@app.route('/setting_update', methods=['POST'])
def setting_update():
	data = request.get_json()
	post_status = data.get('post_status')
	resident_id = data.get('resident_id')
	number = data.get('number')
	name = data.get('name')
	room_number = data.get('room_number')
	status = data.get('status')
	move_id = data.get('move_id')
	move_name = data.get('move_name')
	move_number = data.get('move_number')
	move_room_number = data.get('move_room_number')
	move_status = data.get('move_status')
	if post_status == 'update': #入居者の状態を更新する場合
		#going_to_aloneのみを変更する それ以外はsetting.htmlでdisplay:none;に設置しているため、選択した初期値のまま
		cursor.execute("UPDATE resident SET name = '%s',number = %s,number_people=%s,going_to_alone='%s',reason='exist' WHERE id = %s" % (name,number,room_number,status,resident_id))
		connection.commit()
	elif post_status == 'disappear': #入居者を退去させる場合
		cursor.execute("SELECT number FROM resident WHERE reason = 'not_exist' order by number DESC") #データベースに登録されている非入居者データの一番後ろの部屋番号を取得
		last_num = int(cursor.fetchone()[0]) + 1
		#選択した入居者をその部屋番号のデータに登録し、非入居者とする
		cursor.execute("UPDATE resident SET number = %s, reason = 'not_exist' WHERE id = %s" % (last_num,resident_id))
		connection.commit()
		#先ほどまで入居していた部屋番号には空のデータを追加
		cursor.execute("INSERT INTO resident(name,number,number_people,going_to_alone,card_id) value('None',%s,%s,'None','1')" % (number,room_number))
		connection.commit()
	elif post_status == 'move': #入居者の部屋を移動させる場合
		#移動先のデータと移動するデータを入れ替える
		cursor.execute("UPDATE resident SET name = '%s',number = %s, number_people = %s,going_to_alone = '%s' WHERE id = %s" % (move_name,number,room_number,move_status,move_id))
		connection.commit()
		#移動するresidentデータの更新
		cursor.execute("UPDATE resident SET name = '%s',number = %s,number_people = %s,going_to_alone = '%s' WHERE id = %s" % (name,move_number,move_room_number,status,resident_id))
		connection.commit()
	return jsonify({'status': 'success'})
#共有スペースの新規、更新、削除の処理
@app.route('/setting_space', methods=['POST'])
def setting_space():
	data = request.get_json()
	post_status = data.get('space_status')
	post_name = data.get('space_name')
	post_update_name = data.get('update_space_name')
	post_new_name = data.get('new_space_name')
	if post_status == 'update': #送られてきたデータを更新
		cursor.execute("UPDATE space_data SET space_name = '%s' WHERE space_name = '%s'" % (post_update_name,post_name))
		connection.commit()
	elif post_status == 'delete': #送られてきたデータを削除
		cursor.execute("DELETE FROM  space_data WHERE space_name = '%s'" % (post_name))
		connection.commit()
	elif post_status == 'new': #送られてきたデータを追加
		cursor.execute("INSERT INTO space_data(space_name) VALUE('%s')" % (post_new_name))
		connection.commit()
	return jsonify({'status': 'success'})
#備考テンプレートの新規、更新、削除の処理
@app.route('/setting_remark', methods=['POST'])
def setting_remark():
        data = request.get_json()
        post_status = data.get('remark_status')
        post_remark = data.get('remark')
        post_update_remark = data.get('update_remark')
        post_new_remark = data.get('new_remark')
        if post_status == 'update': #送られてきたデータの更新
                cursor.execute("UPDATE remarks SET remark = '%s' WHERE remark = '%s'" % (post_update_remark,post_remark))
                connection.commit()
        elif post_status == 'delete': #送られてきたデータを削除
                cursor.execute("DELETE FROM remarks WHERE remark = '%s'" % (post_remark))
                connection.commit()
        elif post_status == 'new': #送られてきたデータを追加
                cursor.execute("INSERT INTO remarks(remark) VALUE('%s')" % (post_new_remark))
                connection.commit()
        return jsonify({'status': 'success'})

#homeページの処理
@app.route('/home_submit', methods=['POST'])
def submit_form():
	now = datetime.datetime.now()
	day = now.strftime("%Y-%m-%d")
	time = now.strftime("%H:%M:%S")
	data = request.get_json()
	post_resident = data.get('resident_id')
	post_space = data.get('space_name')
	post_rental_start = data.get('rental_start_time')
	post_rental_end = data.get('rental_end_time')
	post_reason = data.get('reason')
	post_go_out = data.get('go_out')
	post_go_out_reason = data.get('go_out_reason')
	staff_name = data.get('staff_name')
	create_space = data.get('create_space')
	staff_id = data.get('staff_id')
	staff_rental_start = data.get('staff_rental_start')
	staff_rental_end = data.get('staff_rental_end')
	staff_reason = data.get('staff_reason')
	mail = data.get('mail')
	mail_id = data.get('mail_id')
	status = data.get('status')
	login_staff_id = data.get('login_staff_id')
	day_name = 'exit_day'
	time_name = 'exit_time'
	if post_go_out == 'return':
		day_name = 'entrance_day'
		time_name = 'entrance_time'
	if status == 'complete' and mail_id is not None:
		cursor.execute("UPDATE resident_mail SET status = 'complete',check_staff = '%s' WHERE id = %s" % (staff_name, mail_id));
		connection.commit()
	elif mail == 'mail':
		cursor.execute("INSERT INTO resident_mail(resident_id,reason,keep_mail_day,staff_name,status) VALUES(%s,'%s','%s','%s','keep')" % (post_resident,post_go_out_reason,day,staff_name));
		connection.commit()
	elif create_space is not None and create_space != '':
		print('is not none')
		cursor.execute("INSERT INTO space_data(space_name) VALUES('%s')" % (create_space))
		connection.commit()
	elif post_resident != '' and post_go_out != '' and post_space == '' or post_resident != '' and post_go_out != '' and post_space is None:
		cursor.execute("SELECT * FROM resident WHERE id = '%s'" % (post_resident))
		select_resident = cursor.fetchone()
		event = [post_go_out,day,select_resident[4],time,post_resident,select_resident[1],post_go_out_reason,staff_name]
		SwitchView.insert_door(event)
	elif  post_resident != '' and post_go_out == '' and post_space != '' and staff_id == '':
		print('space add')
		cursor.execute("""
		SELECT * FROM space_rental
		WHERE
 		( (start_time <= '%s' AND end_time >= '%s')
  		OR
  		(start_time >= '%s' AND end_time <= '%s')
  		OR
  		(start_time <= '%s' AND end_time >= '%s' AND end_time >= '%s')
  		OR
  		(start_time >= '%s' AND end_time >= '%s' AND start_time <= '%s') ) AND space_name = '%s'  AND start_time LIKE '%s' 
		""" % (post_rental_start,post_rental_end,post_rental_start,post_rental_end,post_rental_start,post_rental_end,post_rental_start,post_rental_start,post_rental_end,post_rental_end,post_space,(day + '%')));
		calendar_check = cursor.fetchall()
		if calendar_check == ():			
			cursor.execute("""
			INSERT INTO space_rental (staff_or_resident,user_id,date_time,start_time,end_time,space_name,reason) 
			VALUES('resident',%s,'%s','%s','%s','%s','%s')"""
		 	% (post_resident,(day + ' ' + time),post_rental_start,post_rental_end,post_space,post_reason))
			connection.commit()
		elif calendar_check != ():
			print('test')
	elif post_go_out == '' and post_space != '' and staff_id != '' and post_resident == '':
		cursor.execute("""
                SELECT * FROM space_rental
                WHERE
                ( (start_time <= '%s' AND end_time >= '%s')
                OR
                (start_time >= '%s' AND end_time <= '%s')
                OR
                (start_time <= '%s' AND end_time >= '%s' AND end_time >= '%s')
                OR
                (start_time >= '%s' AND end_time >= '%s' AND start_time <= '%s') ) AND space_name = '%s'  AND start_time LIKE '%s'
                """ % (post_rental_start,post_rental_end,post_rental_start,post_rental_end,post_rental_start,post_rental_end,post_rental_start,post_rental_start,post_rental_end,post_rental_end,post_space,(day + '%')));
		calendar_check = cursor.fetchall()
		if calendar_check == ():
			cursor.execute("""INSERT INTO space_rental 
			(staff_or_resident,user_id,date_time,start_time,end_time,space_name,reason) 
			VALUES('staff',%s,'%s','%s','%s','%s','%s')""" 
			% (staff_id,(day + ' ' + time),staff_rental_start,staff_rental_end,post_space,staff_reason))
			connection.commit()
		elif calendar_check != ():
			print('test')
	return jsonify({'status': 'success'})

@app.route('/<staff_id>/mail/<resident_id>/<mail_status>', methods=['POST','GET'])
def mail_view(staff_id,resident_id,mail_status):
	select_value = 1
	if mail_status == 'all_record':
		select_value = 0
	
	if  resident_id == '-1':
		cursor.execute(
		"""
		SELECT *
		FROM (
		SELECT resident_mail.*,
                resident.name AS resident_name,
		CASE WHEN status = '%s' THEN 1 ELSE 0 END AS is_kept
		FROM resident_mail
		LEFT JOIN resident ON resident_mail.resident_id = resident.id
		ORDER BY resident_mail.keep_mail_day DESC
		) AS subquery
		WHERE is_kept = %s
		"""
		% (mail_status,select_value))
		all_mail = cursor.fetchall()
	elif resident_id != '-1':
		cursor.execute(
		"""
		SELECT *
		FROM (
		SELECT resident_mail.*,
		resident.name AS resident_name,
		CASE WHEN status = '%s' THEN 1 ELSE 0 END AS is_kept
		FROM resident_mail
		LEFT JOIN resident ON resident_mail.resident_id = resident.id
		ORDER BY resident_mail.keep_mail_day DESC
		) AS subquery
		WHERE is_kept = %s
		AND
		subquery.resident_id = %s
		"""
		% (mail_status,select_value,resident_id))
		all_mail = cursor.fetchall()
	residents = SwitchView.all_residents()
	cursor.execute("SELECT * FROM staff")
	staff_data = cursor.fetchall()
	login_staff = SwitchView.serch_staff(staff_id)
	page = request.args.get(get_page_parameter(), type=int, default=1)
	limit = all_mail[(page -1)*10:page*10]
	pagination = Pagination(page=page, total=len(all_mail))
	return render_template('mail.html',staff_id=staff_id,login_staff=login_staff,residents=residents,all_mail=limit,pagination=pagination, page=page)

@app.route('/<staff_id>/<space_name>/<day>', methods=['POST','GET'])
def return_space_data(staff_id,space_name,day):

	cursor.execute("""
      SELECT
      resident.name,
      staff.name,
      space_rental.start_time,
      space_rental.end_time,
      space_rental.reason,
      staff.id AS user_id,
      resident.id AS user_id
      FROM space_rental
      LEFT JOIN staff ON space_rental.user_id = staff.id AND space_rental.staff_or_resident = 'staff'
      LEFT JOIN resident ON space_rental.user_id = resident.id AND space_rental.staff_or_resident = 'resident'
      WHERE space_rental.space_name = '%s' and space_rental.start_time LIKE '%s' ORDER BY space_rental.start_time;
    """ % (space_name, (day + '%')))
	space_data = cursor.fetchall()
	now = datetime.datetime.now()
	day = now.strftime("%Y-%m-%d")
	time = now.strftime("%H:%M:%S")
	cursor.execute(""" 
        SELECT cr.id,         
        cr.datetime,         
        cr.type,         
        MAX(cr.idm) AS max_idm,         
        MAX(c.id) AS return_id,         
        MAX(c.datetime) AS return_datetime,         
        MAX(c.type) AS return_type,         
        MAX(c.idm) AS return_idm 
        FROM card_record AS cr LEFT JOIN card_record AS c ON cr.idm = c.idm AND c.datetime > cr.datetime WHERE cr.datetime 
        LIKE '%s'   AND cr.type = 'go' GROUP BY cr.id HAVING MAX(c.id) IS NULL
        """ % (day + '%'))
	go_resident = list(chain(*cursor.fetchall()))
	current_year = datetime.datetime.now().year
	current_month = datetime.datetime.now().month
	calendar_month = f"{current_year}-{current_month:02d}"
	space_rental_all = ''
	all_data = []

	for i in range(3, 11):
		data = resident_data(str(i))
		all_data.append(data)
	all_space = all_space_name()
	cursor.execute("""
        SELECT space_name,start_time,end_time FROM space_rental
        WHERE start_time >= '%s' OR end_time >= '%s'
        """ % (day + ' ' + time[:-3],day + ' ' + time[:-3]))
	db_check=cursor.fetchall()
	cursor.execute("SELECT * FROM staff")
	staff_data = cursor.fetchall()
	login_staff = SwitchView.serch_staff(staff_id)
	return render_template('home.html',staff_id=staff_id,login_staff=login_staff, all_data=all_data,space_data=space_data,
	space_name=space_name,all_space=all_space,day=day,staff_data=staff_data,space_rental_all=space_rental_all,select_month='',
	go_resident=go_resident,db_check=db_check)

@app.route('/<staff_id>/<select_month>/calendar', methods=['POST','GET'])
def calendar_data(staff_id, select_month):
	cursor.execute("""
	SELECT
	space_rental.*,
	staff.name,
	resident.name
	FROM
	space_rental
	LEFT JOIN staff ON space_rental.user_id = staff.id AND space_rental.staff_or_resident = 'staff'
	LEFT JOIN resident ON space_rental.user_id = resident.id AND space_rental.staff_or_resident = 'resident'
	where space_rental.start_time like '%s'
	ORDER BY start_time ASC
	""" % (select_month + '%'))
	space_rental_all = cursor.fetchall()
	now = datetime.datetime.now()
	day = now.strftime("%Y-%m-%d")
	time = now.strftime("%H:%M:%S")
	cursor.execute(""" 
        SELECT cr.id,         
        cr.datetime,         
        cr.type,         
        MAX(cr.idm) AS max_idm,         
        MAX(c.id) AS return_id,         
        MAX(c.datetime) AS return_datetime,         
        MAX(c.type) AS return_type,         
        MAX(c.idm) AS return_idm 
        FROM card_record AS cr LEFT JOIN card_record AS c ON cr.idm = c.idm AND c.datetime > cr.datetime WHERE cr.datetime 
        LIKE '%s'   AND cr.type = 'go' GROUP BY cr.id HAVING MAX(c.id) IS NULL
        """ % (day + '%'))

	go_resident = list(chain(*cursor.fetchall()))
	all_data = []
	for i in range(3, 11):
		data = resident_data(str(i))
		all_data.append(data)
	all_space = all_space_name()
	cursor.execute("""
        SELECT space_name,start_time,end_time FROM space_rental
        WHERE start_time >= '%s' OR end_time >= '%s'
        """ % (day + ' ' + time[:-3],day + ' ' + time[:-3]))
	db_check=cursor.fetchall()
	cursor.execute("SELECT * FROM staff")
	staff_data = cursor.fetchall()
	login_staff = SwitchView.serch_staff(staff_id)
	return render_template('home.html',staff_id=staff_id,login_staff=login_staff, all_data=all_data,space_data='',
	space_name='',all_space=all_space,day='',staff_data=staff_data,space_rental_all=space_rental_all,select_month=select_month,
	go_resident=go_resident,db_check=db_check)

if __name__ == "__main__":
    app.run(port = 8000, debug=True)
