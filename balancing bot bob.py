import math
import hub
import time

FACE = hub.Image("99000:97007:00009:99007:97000")
FACE_SURPRISED = hub.Image("89800:89809:00009:89809:89800")
ARROW_UP = hub.Image.ARROW_W
LINE_TURN_ICON = hub.Image("00000:06960:99999:06960:00000")
SPIN_ICON = hub.Image("00000:06960:09990:06960:00000")
SQUARE_ICON = hub.Image.SQUARE
CIRCLE_ICON = hub.Image("08980:80008:90009:80008:08980")
LINE_ICON = hub.Image("00000:00000:99999:00000:00000")


def bound(n, lo, hi):
    return min(max(round(n), lo), hi)


class PidLoop:
    def __init__(self, p, i, d):
        self.p = p
        self.i = i
        self.d = d
        self.clear()

    def step(self, target, measured, dt):
        err = target - measured
        self.acc += err * dt
        self.rate = (err - self.prev) / dt
        self.prev = err
        return self.p * err + self.i * self.acc + self.d * self.rate

    def clear(self):
        self.rate = 0
        self.acc = 0
        self.prev = 0


class Step:
    def __init__(self, length, blocking=True, repeat=False):
        self.length = length
        self.blocking = blocking
        self.repeat = repeat
        self.elapsed = 0

    def begin(self, bot):
        pass

    def finish(self, bot):
        pass

    def tick(self, dt, bot):
        if self.elapsed == 0:
            self.begin(bot)
        self.elapsed += dt
        if self.elapsed >= self.length:
            self.elapsed = 0
            self.finish(bot)
            return False
        return True

    def waits(self):
        return self.blocking

    def repeats(self):
        return self.repeat


class ShowFace(Step):
    def __init__(self, img, repeat=False):
        super().__init__(0, True, repeat)
        self.img = img

    def begin(self, bot):
        bot.draw(self.img)


class Pause(Step):
    def __init__(self, length, repeat=False):
        super().__init__(length, True, repeat)


class Drive(Step):
    def __init__(self, pct=50, length=0, blocking=True, repeat=False):
        super().__init__(length, blocking, repeat)
        self.pct = bound(pct, -100, 100) / 100 * 35

    def finish(self, bot):
        if self.length > 0:
            bot.speed_target = 0

    def tick(self, dt, bot):
        bot.speed_target = self.pct
        return super().tick(dt, bot)


class Rotate(Step):
    def __init__(self, deg, pct=50, blocking=True, repeat=False):
        length = (abs(deg) / 360 * 1.5) * (100 / bound(pct, -100, 100))
        super().__init__(length, blocking, repeat)
        self.delta = deg * 4

    def tick(self, dt, bot):
        bot.yaw_target = bot.yaw_target + self.delta * (dt / self.length)
        return super().tick(dt, bot)


class Sequence:
    def __init__(self, bot):
        self.queue = []
        self.bot = bot

    def push(self, items):
        if isinstance(items, list):
            self.queue.extend(items)
        else:
            self.queue.append(items)

    def replace(self, items):
        self.flush()
        self.push(items)
        self.tick(0)

    def flush(self):
        self.bot.speed_target = 0
        self.queue = []

    def tick(self, dt):
        for item in self.queue:
            if not item.tick(dt, self.bot):
                self.queue.remove(item)
                if item.repeats():
                    self.queue.append(item)
            if item.waits():
                break


class Balancer:
    GYRO_BLEND = 0.995
    ACCEL_BLEND = 1 - GYRO_BLEND
    TO_DEG = 180 / math.pi

    def __init__(self, left, right, pitch_offset=0):
        self.left = left
        self.right = right
        self.pitch_offset = pitch_offset
        self.speed_target = 0
        self.yaw_target = 0
        self.pitch_ctrl = PidLoop(13.5, 155, 0.19)
        self.speed_ctrl = PidLoop(0.04, 0.03, 0.00055)
        self.yaw_ctrl = PidLoop(0.9, 2, 0.01)
        self.sequence = Sequence(self)

    def pitch(self):
        try:
            dt = time.ticks_diff(time.ticks_us(), self._gyro_t) * 0.000001
            self._gyro_t = time.ticks_us()
            a = hub.motion.accelerometer()
            from_gyro = self._angle + hub.motion.gyroscope()[1] * dt
            from_accel = -math.atan2(a[2], math.sqrt(a[0] * a[0] + a[1] * a[1])) * self.TO_DEG
            self._angle = self.GYRO_BLEND * from_gyro + self.ACCEL_BLEND * from_accel
        except AttributeError:
            self._angle = hub.motion.yaw_pitch_roll()[2] - 90
            self._gyro_t = time.ticks_us()
        return self._angle

    def yaw(self):
        return -(self.left.device.get()[1] + self.right.device.get()[1])

    def speed(self):
        return (self.right.device.get()[0] - self.left.device.get()[0]) / 2

    def drive_motors(self, power, steer=0):
        self.left.pwm(bound(power - steer, -127, 127))
        self.right.pwm(-bound(power + steer, -127, 127))

    def draw(self, img):
        hub.display.show(img)

    def run(self):
        upright = False
        self.draw(ARROW_UP)
        t0 = time.ticks_us()

        while True:
            dt = time.ticks_diff(time.ticks_us(), t0) * 0.000001
            t0 = time.ticks_us()
            angle = self.pitch()

            if upright:
                if abs(angle) < 45:
                    self.sequence.tick(dt)
                    lean = self.speed_ctrl.step(self.speed_target, self.speed(), dt)
                    power = self.pitch_ctrl.step(lean + self.pitch_offset, angle, dt)
                    steer = self.yaw_ctrl.step(self.yaw_target, self.yaw(), dt)
                    self.drive_motors(power, steer)
                else:
                    upright = False
                    self.sequence.flush()
                    self.drive_motors(0)
                    self.pitch_ctrl.clear()
                    self.speed_ctrl.clear()
                    self.yaw_ctrl.clear()
                    self.draw(ARROW_UP)
            else:
                if abs(angle) < 3:
                    upright = True
                    self.draw(FACE)


bot = Balancer(hub.port.B, hub.port.F, 1.6)

demos = [
    ShowFace(FACE),
    [
        ShowFace(LINE_ICON),
        Pause(2),
        ShowFace(FACE),
        Drive(70, 5, repeat=True),
        Drive(-70, 5, repeat=True),
    ],
    [
        ShowFace(LINE_TURN_ICON),
        Pause(2),
        ShowFace(FACE, repeat=True),
        Drive(85, 3, repeat=True),
        ShowFace(FACE_SURPRISED, repeat=True),
        Rotate(180, 100, blocking=False, repeat=True),
        Drive(-80, 3, repeat=True),
        ShowFace(FACE, repeat=True),
    ],
    [
        ShowFace(SQUARE_ICON),
        Pause(2),
        ShowFace(FACE),
        Drive(80, 4, repeat=True),
        Rotate(90, repeat=True),
    ],
    [
        ShowFace(CIRCLE_ICON),
        Pause(2),
        ShowFace(FACE),
        Drive(100, 5, blocking=False, repeat=True),
        Rotate(360, 20, blocking=False, repeat=True),
    ],
    [
        ShowFace(SPIN_ICON),
        Pause(2),
        ShowFace(FACE),
        Rotate(360, 80, repeat=True),
    ],
]

demo_i = 0


def left_press(ms):
    global demo_i
    if ms == 0:
        demo_i = (demo_i + 1) % len(demos)
        bot.sequence.replace(demos[demo_i])


def right_press(ms):
    global demo_i
    if ms == 0:
        demo_i = (demo_i - 1) % len(demos)
        bot.sequence.replace(demos[demo_i])


hub.button.left.on_change(left_press)
hub.button.right.on_change(right_press)
hub.led(0)

bot.run()
