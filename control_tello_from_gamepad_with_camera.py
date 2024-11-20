#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import time
from djitellopy import Tello, TelloException
import pygame
from pygame.locals import JOYAXISMOTION, JOYBUTTONDOWN
from functools import cache
import cv2
from threading import Thread
from queue import Queue


class TelloCameraStream:
    def __init__(self, ip, port):
        self.ip = ip
        self.port = port
        self.is_running = True  # ストリームが動作中かどうか
        self.is_recording = False  # 録画中かどうか
        self.is_take_picture = False  # 写真を撮るかどうか
        # カメラストリームを取得
        self.cap = cv2.VideoCapture(f'udp://{ip}:{port}')
        # 画像の幅と高さを設定
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH) / 2)
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT) / 2)
        # フレームレートを取得
        self.fps = int(self.cap.get(cv2.CAP_PROP_FPS))
        self.video_writer = None
        self.frame_name = f'Tello {self.ip}'
        self.frame_queue = Queue(maxsize=1)  # 最新フレームを保持するキュー
        # フレームをキャプチャするスレッドを開始
        self.thread = Thread(target=self._capture_frames, daemon=True)
        self.thread.start()


    def _capture_frames(self):
        while self.is_running:
            ret, frame = self.cap.read()
            if ret:
                # 最新フレームのみを保持
                if not self.frame_queue.empty():
                    self.frame_queue.get_nowait()
                self.frame_queue.put(frame)


    def display_stream(self):
        if self.is_running:
            if not self.frame_queue.empty():
                frame = self.frame_queue.get()
                # フレームのリサイズ
                resized_frame = cv2.resize(frame, (self.width, self.height), interpolation=cv2.INTER_LINEAR)
                cv2.imshow(self.frame_name, resized_frame)

                # 録画中ならフレームを保存
                if self.is_recording and self.video_writer:
                    self.video_writer.write(resized_frame)

                # 写真を撮る処理
                if self.is_take_picture:
                    now = time.strftime('%Y%m%d_%H%M%S')
                    ip_suffix = self.ip.split('.')[-1]
                    cv2.imwrite(f'picture_{ip_suffix}_{now}.png', resized_frame)
                    print(f'[INFO] Picture saved as picture_{ip_suffix}_{now}.png')
                    self.is_take_picture = False

                # ESCキーが押されたら、また、ウィンドウが終了したらストップ
                if cv2.waitKey(1) & 0xFF == 27 or cv2.getWindowProperty(self.frame_name, cv2.WND_PROP_AUTOSIZE) == -1:
                    self.stop()


    def take_picture(self):
        self.is_take_picture = True  # 写真を撮るフラグを立てる


    def start_recording(self):
        now = time.strftime('%Y%m%d_%H%M%S')
        file_name = f'video_{self.ip.split(".")[-1]}_{now}.avi'

        # ビデオライターを初期化して録画を開始
        self.video_writer = cv2.VideoWriter(
            file_name,
            cv2.VideoWriter_fourcc(*'XVID'),
            self.fps,
            (self.width, self.height)
        )
        self.is_recording = True
        print(f"[INFO] Recording started: {file_name}")


    def stop_recording(self):
        if self.is_recording and self.video_writer:
            self.video_writer.release()  # 録画を停止
            self.video_writer = None
        self.is_recording = False
        print("[INFO] Recording stopped")


    def stop(self):
        self.is_running = False  # ストリームを停止
        self.thread.join()  # スレッドを終了
        if self.cap.isOpened():
            self.cap.release()  # カメラを開放
        cv2.destroyAllWindows()  # ウィンドウを閉じる
        if self.is_recording and self.video_writer:
            self.video_writer.release()  # 録画を停止

    # ストリームが動作中かどうかを返す
    def is_run(self):
        return self.is_running



def main():
    LOCAL_IP = '192.168.13.3'
    LOCAL_PORT_VIDEO = '11111'

    # pygameの初期化
    pygame.init()

    # Joystickオブジェクトの作成
    joystick = pygame.joystick.Joystick(0)
    joystick.init()
    print(f'Gamepad Name: {joystick.get_name()}')

    # Telloの初期化
    # Wi-Fiアクセスポイントへ接続する設定（Wi-Fi子機になるモード）にしている場合は
    # hostを指定してIPアドレスは現物に合わせる
    Tello.RETRY_COUNT = 1          # retry_countは応答が来ないときのリトライ回数
    Tello.RESPONSE_TIMEOUT = 0.01  # 応答が来ないときのタイムアウト時間
    tello = Tello(host=LOCAL_IP)

    try:
        tello.connect()  # Telloへ接続
        tello.streamoff()  # 誤動作防止の為、最初にOFFする
        tello.streamon()  # 画像転送をONに
        # カメラストリームを初期化
        camera_stream = TelloCameraStream(LOCAL_IP, LOCAL_PORT_VIDEO)
    except KeyboardInterrupt:
        print('\n[Finish] Press Ctrl+C to exit')
        sys.exit()
    except TelloException:
        print('\n[Finish] Connection timeout')
        sys.exit()

    while True:
        try:
            # カメラストリームを表示
            camera_stream.display_stream()
            # イベントの取得
            for event in pygame.event.get():
                # イベントがスティック操作の場合
                if event.type == pygame.locals.JOYAXISMOTION:
                    send_tello(tello,
                               'rc',
                               map_axis(round(joystick.get_axis(3), 2)),
                               map_axis(-round(joystick.get_axis(1), 2)),
                               map_axis(-round(joystick.get_axis(4), 2)),
                               map_axis(round(joystick.get_axis(0), 2))
                    )
                # イベントがボタン操作の場合
                elif event.type == pygame.locals.JOYBUTTONDOWN:
                    if joystick.get_button(7):
                        send_tello(tello, 'takeoff')
                    elif joystick.get_button(6):
                        send_tello(tello, 'land')
                    elif joystick.get_button(3):
                        send_tello(tello, 'flip_forward')
                    elif joystick.get_button(0):
                        send_tello(tello, 'flip_back')
                    elif joystick.get_button(2):
                        send_tello(tello, 'flip_left')
                    elif joystick.get_button(1):
                        send_tello(tello, 'flip_right')
                    elif joystick.get_button(5):
                        camera_stream.take_picture()
                    elif joystick.get_button(4):
                        if not camera_stream.is_recording:
                            camera_stream.start_recording()
                        else:
                            camera_stream.stop_recording()
                    elif joystick.get_button(8):
                        print('[Finish] Press emergency button to exit by Gamepad')
                        send_tello(tello, 'emergency')
                        camera_stream.stop()
                        term_process(tello)

            if not camera_stream.is_run():
                send_tello(tello, 'emergency')
                term_process(tello)
        # Ctrl+Cが押された
        except KeyboardInterrupt:
            print('[Warnning] Press Ctrl+C to exit')
            send_tello(tello, 'emergency')
            camera_stream.stop()
            term_process(tello)


def term_process(tello):
    print('[Finish] Game finish!!')
    tello.streamoff()
    tello.end()
    sys.exit()


# send_rc_control(left_right, forward_backward, up_down, yaw)
# left_right                 left -100 ...  100 right
# forward_backward           forw  100 ... -100 backw
# up_down                      up  100 ... -100 down
# yaw (rotate)      counter clock -100 ...  100 clock
def send_tello(tello, cmd, left_right=0, forward_backward=0, up_down=0, yaw=0):
    try:
        if cmd == 'rc':
            tello.send_rc_control(left_right, forward_backward, up_down, yaw)
        elif cmd == 'land':
            tello.land()
        elif cmd == 'takeoff':
            tello.takeoff()
        elif cmd == 'flip_forward':
            tello.flip_forward()
        elif cmd == 'flip_back':
            tello.flip_back()
        elif cmd == 'flip_left':
            tello.flip_left()
        elif cmd == 'flip_right':
            tello.flip_right()
        elif cmd == 'emergency':
            print('\nEmergency Stop!!\n')
            tello.emergency()
            print(f'[Battery] {tello.get_battery()}%')
    except TelloException:
        print('[ERROR] Error occurred when sending tello command ')


# スティックの出力数値を調整
# -1.0 ~ 1.0 の数値を -100 ~ 100 の数値に変換
# 線形補間を用いて計算している
@cache
def map_axis(val):
    # 小数点以下2桁に四捨五入

    # 入力の最小値と最大値
    in_min = -1
    in_max = 1
    # 出力の最小値と最大値
    out_min = -100
    out_max = 100
    # 線形補間を用いて計算
    return int(out_min + (out_max - out_min) * ((val - in_min) / (in_max - in_min)))


if __name__ == '__main__':
    main()
