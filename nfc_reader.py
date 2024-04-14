import binascii
import nfc
import os
import sys
import subprocess
import requests
import datetime
import time
import timeout_decorator
import asyncio
import aiomysql
from nfc.clf import RemoteTarget
import json, requests
from pydub import AudioSegment
from pydub.playback import play



#switchbotのパラメーター（要書き換え）
DEVICEID="switch bot　id"
ACCESS_TOKEN="switch bot access token"
API_BASE_URL="https://api.switch-bot.com"

#raspberry piからswitchbotへリクエストを送る
headers = {
    # ヘッダー
    'Content-Type': 'application/json; charset: utf8',
    'Authorization': ACCESS_TOKEN
    }
url = API_BASE_URL + "/v1.0/devices/" + DEVICEID + "/commands"
body = {
    # 操作内容
    "command":"turnOn",
    "parameter":"default",
    "commandType":"command"
    }
ddd = json.dumps(body)
print('開始')


class MyCardReader(object):
    def __init__(self):
            self.idm_data = '' #カードのidをここに格納
            self.resident_id = '' #カードをかざした入居者のidを格納する値
            self.scan_card_name = '' #カードをかざした入居者の名前を格納する値
            #self.card_type = input('go or return')
            self.card_type = 'go' #入退のどちらかを決める値
            self.last_time = datetime.datetime.now() #同じカードを連続で通した際の秒差
            self.motor_run = '' #モータが動いたかの値を入れる。switchbot では使用しない
            self.move_staff = ''

    #上で用意したswitchbotのデータのリクエストを飛ばす
    async def send_command_async(self):
        #print('start2')
        res = await asyncio.to_thread(requests.post, url, data=ddd, headers=headers)
    #非同期でsound_play()を実行する
    async def sound_play_async(self):
        #print('start1')
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.sound_play)
    #/home/pi/button1.mp3を鳴らす
    def sound_play(self):
        sound = AudioSegment.from_mp3("/home/pi/button1.mp3")
        play(sound)
    #self.idm_dataをもとに入居者のデータを獲得する
    def resident_select(self):
        
        command = [
            "社内データベースへアクセスするAPI"
            ]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        json_string = result.stdout

        json_data = json.loads(json_string)
        return_data = json_data.get("return")
        print('return_data: ',return_data)
        if return_data != []:
            self.scan_card_name = return_data[0].get("name")
        print(self.scan_card_name)
    #非同期でmysqlに接続し、受け取ったデータにひとり外出可能な入居者がいるか・職員かを識別。
    async def db_set(self,loop,tag,time_data):
        pool = await aiomysql.create_pool(
        host=MySQL IPAddress,
        user='root',
        password='mypassword',
        db='exit_entrance_management',
        charset='utf8',
        loop=loop,
        )
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute('set global wait_timeout=86400')
                await cur.execute("select * from resident where going_to_alone like '一人外出可%' and name = '{}'".format(self.scan_card_name))
                result = await cur.fetchone()
                if result is not None:
                    await asyncio.gather(self.send_command_async(), self.sound_play_async())
                    #ひとり外出可能な入居者であればカードを通した時間と入館か帰館かを記録
                    await cur.execute("""INSERT INTO card_record(datetime,type,idm,first_time) VALUE('%s','%s','%s','%s')
                    """ % (datetime.datetime.now(),self.card_type,self.scan_card_name,datetime.datetime.now()))
                    await conn.commit()
                    final_time = datetime.datetime.now()
                    print('スイッチの信号を送信',final_time - time_data)
                elif result is None:
                    await cur.execute("select * from staff_card where card_id = '{}'".format(self.idm_data))
                    staff_card = await cur.fetchone()
                    if staff_card is not None:
                        print('move staff: ',self.move_staff)
                        self.move_staff = 'staff open door'
                        await asyncio.gather(self.send_command_async(), self.sound_play_async())
                        return
    #カードをかざし、読み取り上記の処理を行う
    async def nfc_start(self,loop):
        try:
            clf = nfc.ContactlessFrontend('usb')
            print(clf)
            tag = clf.connect(rdwr={
             'on-connect': lambda tag: False
            })
            print(tag)
            print(str(tag)[0:7] in 'Type3Tag')
            if str(tag)[0:7] in 'Type3Tag': #Felcaカードでない場合
                self.idm_data = str(binascii.hexlify(tag.idm))[2:-1]
            elif str(tag)[0:7] in 'Type2Tag':
                self.idm_data = str(tag)[-8:]
            start_time = datetime.datetime.now()
            self.resident_select()
            end_time = datetime.datetime.now()
            #print('経過時間:', end_time - start_time)
            now = datetime.datetime.now()
            elapsed_time = (now - self.last_time).total_seconds()
            if elapsed_time < 4.0 and self.idm_data == str(binascii.hexlify(tag._nfcid))[2:-1]:
                clf.close()
                self.motor_run = 'no'
            else:
                await self.db_set(loop,tag,start_time)
                self.last_time = now
                self.motor_run = 'ok'
            clf.close()
            self.scan_card_name = ''
        except AttributeError as e:
            print("error",e)
            exit()
    #nfc_start()を呼び出す
    async def main(self,):
        loop = asyncio.get_event_loop()
        await self.nfc_start(loop)
    #職員登録の際のカードを読み取る処理
    def staff_signup(self):
        try:
            clf = nfc.ContactlessFrontend('usb')
            tag = clf.connect(rdwr={
             'on-connect': lambda tag: False
            })
            print(tag)
            self.idm_data = str(binascii.hexlify(tag.idm))[2:-1]
            clf.close()
        except AttributeError as e:
            print("error",e)
            exit()
    #sraff_signup()で受け取ったカードidをreturnする
    def signup_card_data(self):
        #loop = asyncio.get_event_loop()
        #await self.staff_signup(loop)
        self.staff_signup()
        return self.idm_data


#t = MyCardReader()
#while True:
    #asyncio.run(t.main())
#asyncio.run(t.signup_card_data())
