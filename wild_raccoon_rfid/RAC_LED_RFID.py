# Puzzle box control system
__version__ = "v14 05-12-2019"
__author__ = "E. Bridge and J. Huizinga"

# Import necessary libraries
import pygame               # For full screen and sound
import RPi.GPIO as GPIO     # Input output pin controls
import time                 # For delays
import datetime             # For processing time stamps
import collections          # Needed for making an ordered dictionary
import random               # For randomization and shuffling
import traceback            # For logging when the program crashes
import serial               # For reading from the RFID reader

# Constants
MODE = "window"  # Set this to "fullscreen" to enable fullscreen
FRAME_TIME = 50   # Aim for 20 frames per second
NUMBER_OF_RECHECKS = 1
RECHECK_THRESHOLD = 0.1

PRINT_TIME = False

# If you want to stop printing the time, uncomment this next line:
# PRINT_TIME = False

# JH: I don't think absolute paths are necessary on the Raspberry Pi, meaning
# these paths should work, regardless of where the code is run. Please change
# back to absolute paths if this doesn't work.
FOLDER = "./"
CONFIG_FILE = "LED_RFID_ConfigurationFile.txt"
ANIMAL_PARAMS_FILE = "LED_RFID_AnimalFile.txt"
# CONFIG_FILE="exampleExtraTests.txt"
# CONFIG_FILE="exampleFailedBlockDelay.txt"
# CONFIG_FILE="exampleFailedTrialDelay.txt"
# CONFIG_FILE="exampleTrajectory.txt"
DATA_FILE = "results.csv"
DATA_DIR = "."
ERROR_LOG = "error.txt"
# FOLDER="/media/pi/RACCOON5/"
# CONFIG_FILE="/media/pi/RACCOON5/animationsRAC129.txt"
# DATA_FILE="/media/pi/RACCOON5/RAC129Results.txt"
# ERROR_LOG="/media/pi/RACCOON5/error.txt"

# Pin numbers
# PIN_IR_IN=18
# PIN_IR_POWER=4
# PIN_IR_LED=24
PIN_MOTOR_SNAP = 20
PIN_MOTOR_RIGHT = 13
PIN_MOTOR_LEFT = 19
PIN_JOY_RIGHT = 6
PIN_JOY_LEFT = 5
PIN_LED_RIGHT = 1
PIN_LED_LEFT = 2

RFID_TIME_FORMAT = '%m/%d/%Y %H:%M:%S.%f'
LOG_TIME_FORMAT = '%Y-%m-%d %H:%M:%S'

OPPOSITE_ANSWERS = {"R": "L", "L": "R", "X": "X"}
LEGAL_ANSWERS = ["L", "R", "E", "I"]

PAR_KEY = 0
PAR_INIT = 1
PAR_TYPE = 2
PAR_DESC = 3
PAR_RESET = 4

ANIMAL_PARAMS = [
    ("entry_cnt", 0, int, "Entry rewards obtained", True),
    ("push_cnt_e", 0, int, "Training rewards obtained either", False),
    ("push_cnt_r", 0, int, "Training rewards obtained right", False),
    ("push_cnt_l", 0, int, "Training rewards obtained left", False),
    ("train_push_cnt_r", 0, int, "Training preference right", False),
    ("train_push_cnt_l", 0, int, "Training preference left", False),
    ("preference_answer", "X", str, "Preference", False),
    ("curr_test", 0, int, "Current test", False),
    ("failed_blocks", 0, int, "Blocks failed in current test", False),
    ("block_suc_cnt", 0, int, "Blocks succeeded in current test", False),
    ("curr_block", 0, int, "Current block", False),
    ("trial_cnt", 0, int, "Trials performed in current block", False),
    ("trial_suc_cnt", 0, int, "Trials succeeded in current block", False),
    ("failed_trials", 0, int, "Trials failed in current block", False),
    ("failed_curr_trial", 0, int, "Current trial failed", False),
    ("tests_current_session", 0, int, "Tests current session", True),
    ("sliding_window", [], "int_list", "Sliding window", False),
]

GLOBAL_PARAMS = [
    ("previous_shuffle", [], list, "Order of trials", False),
    ("rew_cnt", 0, int, "Total rewards dispensed", True),
]

HEADER = ['Animal_id',
          'Event',
          'Start_time',
          'End_time',
          'Training_push_count',
          'Current_test',
          'Current_block',
          'Current_trial',
          'Failed_current_trial',
          'Failed_trials',
          'Failed_blocks',
          'LED_status',
          'Push',
          'Correct',
          'Reward_count',
          'Successful_trials_in_window']

PUSH_DICT = {'L': 'Left', 'R': 'Right', 'E': 'Either', 'I': 'Input'}

CTRL_QUIT = '\x11\x15\x09\x14'

# JH: Custom exception for reporting failures while reading a tag
class RfidTagParseException(Exception):
    pass


# JH: Class for organizing tag information
class RfidTag:
    def __init__(self):
        self.tag_time_stamp = None
        self.tag_reader_id = None
        self.tag_record_type = None
        self.tag_from_memory = None
        self.tag_number = None

    def init_from_str(self, string):
        split_tag = string.split(' ')
        if len(split_tag) < 5:
            msg = 'String does not have the correct number of fields'
            raise RfidTagParseException(msg)
        # print(split_tag)
        self.tag_record_type = split_tag[0]
        self.tag_reader_id = split_tag[1]
        tag_time = split_tag[2] + " " + split_tag[3]
        try:
            self.tag_time_stamp = parse_time(tag_time)
        except ValueError:
            raise RfidTagParseException('Incorrect format for timestamp')
        self.tag_number = split_tag[4].strip()

    def __str__(self):
        result = ""
        if self.tag_time_stamp is None:
            return result
        result += self.tag_time_stamp.strftime(RFID_TIME_FORMAT) + " "
        result += self.tag_reader_id + " "
        result += self.tag_number
        return result
    
    
# JH: Class for keeping track of the LED status
class LEDS:
    def __init__(self):
        self.left = False
        self.right = False

    def turn_left_on(self):
        self.left = True
        GPIO.output(PIN_LED_LEFT, 1)

    def turn_right_on(self):
        self.right = True
        GPIO.output(PIN_LED_RIGHT, 1)

    def turn_left_off(self):
        self.left = False
        GPIO.output(PIN_LED_LEFT, 0)

    def turn_right_off(self):
        self.right = False
        GPIO.output(PIN_LED_RIGHT, 0)

    def turn_both_on(self):
        self.turn_left_on()
        self.turn_right_on()

    def turn_both_off(self):
        self.turn_left_off()
        self.turn_right_off()

    def set_leds(self, setting):
        if setting == "L":
            self.turn_left_on()
            self.turn_right_off()
        elif setting == "R":
            self.turn_right_on()
            self.turn_left_off()
        elif setting == "E" or setting == "B":
            self.turn_both_on()
        elif setting == "N":
            self.turn_both_off()

    def __str__(self):
        result = "Left: "
        if self.left:
            result += "On"
        else:
            result += "Off"
        result += " Right: "
        if self.right:
            result += "On"
        else:
            result += "Off"
        return result
    

# JH: Class added for reading parameters
class Parameter:
    def __init__(self, name, default, exp, par_type, positional):
        self.name = name
        self.default = default
        self.exp = exp
        self.positional = positional
        self.value = default
        self.parType = par_type


# ============== FUNCTIONS ============== #
def now():
    return datetime.datetime.now()


def sec(seconds):
    return datetime.timedelta(seconds=seconds)


def parse_time(time_str):
    return datetime.datetime.strptime(time_str, RFID_TIME_FORMAT)


def get_trial_index():
    return get_animal_par('trial_cnt') % par['trials_in_block']


def set_global_par(param, value):
    animalDict["GLOBAL"][param] = value


def get_global_par(param):
    return animalDict["GLOBAL"][param]


def increment_global_par(param):
    animalDict["GLOBAL"][param] += 1


def init_global_par():
    animalDict["GLOBAL"] = dict()
    for par_config in GLOBAL_PARAMS:
        animalDict["GLOBAL"][par_config[PAR_KEY]] = par_config[PAR_INIT]


def get_animal_par(param):
    return animalDict[animal_id][param]


def set_animal_par(param, value):
    animalDict[animal_id][param] = value


def increment_animal_par(param):
    animalDict[animal_id][param] += 1


def print_animal_par(animal):
    print("Parameters for animal:", animal)
    for par_config in ANIMAL_PARAMS:
        value = animalDict[animal][par_config[PAR_KEY]]
        print("- " + par_config[PAR_DESC] + ":", value)


def init_animal_par(animal):
    if animal not in animals_seen_this_session:
        write_results_header(get_animal_results_file_name(animal))
        animals_seen_this_session.add(animal)
    if animal not in animalDict:
        print("Detected new animal with ID:", animal)
        animalDict[animal] = dict()
        for par_config in ANIMAL_PARAMS:
            animalDict[animal][par_config[PAR_KEY]] = par_config[PAR_INIT]
    else:
        print("Detected known animal with ID:", animal)
        for par_config in ANIMAL_PARAMS:
            key = par_config[PAR_KEY]
            if key not in animalDict[animal]:
                print("Parameter '" + str(key) + "' not set. Initializing.")
                animalDict[animal][key] = par_config[PAR_INIT]
        print_animal_par(animal)
    if len(get_animal_par('sliding_window')) != par['trials_in_block']:
        set_animal_par('sliding_window', [0] * par['trials_in_block'])


# interrupt detection function
def pushed(channel): 
    global listen    
    global push
    if listen == 1:  # Only do the following if we are listening...
        print("trigger detected...", flush=True)
        if channel == PIN_JOY_LEFT:
            responses = [0]
            for _ in range(NUMBER_OF_RECHECKS):
                time.sleep(0.01)
                responses.append(GPIO.input(PIN_JOY_LEFT))
            # make sure it's a push and not a release
            if sum(responses) <= RECHECK_THRESHOLD: 
                push = "L"
                listen = 0  # turn off listening for interrupts
                # print("Left button pushed " + push)
        if channel == PIN_JOY_RIGHT:
            responses = [0]
            for _ in range(NUMBER_OF_RECHECKS):
                time.sleep(0.01)
                responses.append(GPIO.input(PIN_JOY_RIGHT))
            # make sure it's a push and not a release   
            if sum(responses) <= RECHECK_THRESHOLD:          
                push = "R"
                listen = 0  # turn off listening for interrupts
                # print("Right button pushed " + push)


# Show an image full screen (or not full screen)
def show_img(img):
    global screen
    img1 = pygame.image.load(FOLDER + img)
    screen.blit(img1, (0, 0))
    pygame.display.flip()
    pygame.event.pump()


def custom_bool_cast(string):
    if string.lower() == "false":
        return False
    elif string == "0":
        return False
    else:
        return bool(string)


def play_sound(wav):
    wav_file = FOLDER + wav
    beep = pygame.mixer.Sound(wav_file)
    beep.play()

    
# JH: Code for new parameters  
def reset_params():
    global positionalParameters
    global namedParameters
    positionalParameters = []
    namedParameters = collections.OrderedDict()

    
# JH: Code for new parameters
def add_param(name, default, exp, par_type=int):
    positionalParameters.append(Parameter(name, default, exp, par_type, True))

    
# JH: More code for new parameters
def add_named_param(name, default, exp, par_type=str):
    namedParameters[name] = Parameter(name, default, exp, par_type, False)


def read_rfid():
    """
    Returns the most recently read RFID tag.

    Returns an uninitialized tag if no tags have been detected yet.

    Also sets the oldTag, reliable, last_time_since_unreliable global variables.

    :return: The most recently read RFID tag.
    """
    global oldTag
    global reliable
    global last_time_since_unreliable
    
    if oldTag.tag_number is not None:
        current_delay = now() - oldTag.tag_time_stamp
        # print("current_delay:", current_delay)
        # If the delay between the current reading and the previous reading is
        # too long, our current readings are not considered reliable, and we
        # reset the reliability timer
        if current_delay > sec(par['reliability_delay_threshold']):
            last_time_since_unreliable = now()

        # If we have considered our readings to be reliable for a sufficient
        # amount of time, we consider our current readings as reliable, and we
        # will be willing to switch more reliably
        time_since_unreliable = now() - last_time_since_unreliable
        reliable = time_since_unreliable > sec(par['time_until_reliable'])
    else:
        reliable = True
    
    if ard.inWaiting() == 0:
        # Handle the case in which we obtain no new data
        return oldTag
    msg = ard.readline().decode()
    new_tag = RfidTag()
    try:
        new_tag.init_from_str(msg)
        # The reader and RPi are often not synchronized, so I am just going to
        # assume that the time the tag is read is the current time on the RPi
        new_tag.tag_time_stamp = now()
        oldTag = new_tag
    except RfidTagParseException:
        print("Read something other than an Rfid tag:", msg)
    return new_tag


def get_params():  # open the parameters file and get data
    global par  
    global tests
    global testDict
    global ignored_tags
    # global sliding_window

    reset_params()
    add_param("entry_reward", 2, "Maximum entry rewards")
    add_param("push_reward_e", 4,
              "Maximum screen push rewards (total of both sides)")
    add_param("push_reward_r", 2,
              "Maximum screen push rewards for the right side")
    add_param("push_reward_l", 2,
              "Maximum screen push rewards for the left side")
    add_param("trials_in_block", 12, "Number of trials in a block")
    add_param("loop_test", 0,
              "Which test to loop back to after all are complete")
    add_param("block_suc_thresh", 9,
              "Block success threshold - "
              "minimum number of trials passed to move on")
    add_param("blocks_to_pass", 2,
              "Number of successive successful blocks to move to the next test")
    add_param("fail_delay", 5,
              "Fail delay - "
              "how many seconds to delay testing if an animal fails a trial")
    # addParam("rew_cnt", 0,
    #          "Daily reward count - counts rewards given in a single day")
    add_param("rew_max", 50, "Maximum number of reward allowed in a day")
    add_param("rew_day", 1, "Day of the month ")
    add_param("max_failed_blocks", 0,
              "Number of times a block can be failed before a long timeout.")
    # addParam("failed_blocks", 0,
    #          "Current number of failed blocks (handled by program).")
    add_param("failed_blocks_timeout", 30,
              "Timeout when the maximum number of failed blocks is reached "
              "(in minutes).")
    add_param("max_failed_trails", 0,
              "Number of trails that can be failed before a timeout "
              "(resets every block).")
    add_param("failed_trails_timeout", 60,
              "Timeout when the maximum number of failed trials is reached "
              "(in seconds).")
    add_param("fail_trial_repeat", 0,
              "Number of times trial is repeated when a wrong answer is given.")
    # addParam("failed_curr_trial", 0,
    #          "Wrong answers given on current trial (handled by program).")
    # addParam("failed_trials", 0,
    #          "Wrong answers given in current block (handled by program).")
    add_param("consecutive_block", False,
              ": If set to True, enables consecutive block trails.", bool)
    add_param("rfid_timeout", 5,
              "Time before we consider the current animal as departed "
              "(in seconds).")
    add_param("rfid_new_animal_timeout", 1,
              "Time before we switch to a new animal after old animal is no "
              "longer detected (in seconds).")
    add_param("reliability_delay_threshold", 3,
              "Maximum time between readings before we consider the readings "
              "to be unreliable (in seconds).")
    add_param("time_until_reliable", 10,
              "Time that we need our readings to be reliable before performing "
              "a fast switch (in seconds).")
    add_param("max_tests_session", 1,
              "Maximum tests per session.")
    add_param("between_test_timeout", 0,
              "Timeout applied between tests (in seconds).")
    add_named_param("ignored_tags", "",
                    "The program will not respond to Raccoons with any of "
                    "these tags.")
    # addNamedParam("previous_shuffle", "",
    #               "Order of trials stored from a previous experiment.\n"
    #               "Handled automatically, so it does not need to be altered.")
    add_named_param("tests", "shuffle1",
                    "The ordered sequence of tests to be performed. The\n"
                    "answers for each test should be defined on a separate\n"
                    "line. For example, if your test is named test1, you\n"
                    "should define a list of answers for that test as:\n"
                    "test1=L-L, R-R. The special names \"rand,\" and\n"
                    "\"shuffle\" can be used for random trial selection\n"
                    "from the entire list.")
    img_exp = ("The lists of trials associated with each test. Each trial is\n"
               "an answer-led pair, where the first character determines the\n"
               "correct answer (“R” for right, “L” for left, “E” for either,\n"
               "“I” for input, “S” for same as input, “O” opposite from\n"
               "input) and the second character determines which LEDs will\n"
               "be on (“R” for right, “L” for left, “B” for both, and “N” for\n"
               "neither).")
    add_named_param("shuffle1", "L-L, R-R", img_exp)

    # Read the configuration file, or write a new configuration file if it could
    # not be found.
    print("Reading configuration file:", CONFIG_FILE, flush=True)
    raw_lines = []
    try:
        with open(CONFIG_FILE, 'r') as pFile:
            raw_lines = pFile.readlines()
            pFile.close()
    except FileNotFoundError:
        print("ERROR: Configuration file", CONFIG_FILE, "not found.")
        print("Creating new configuration file.")
        print("Please check the configuration and restart.")
        write_current_params()
        exit()

    # Remove the values for the example parameters; read them from file instead
    namedParameters["tests"].value = ""
    del namedParameters["shuffle1"]
    
    # Remove comments and empty lines from lines
    lines = []
    for line in raw_lines:
        line = line.strip()
        if len(line) == 0:
            continue
        if line[0] == "#":
            continue
        lines.append(line)

    # Read positional parameters
    param = []
    line_index = 0
    while line_index < len(positionalParameters) and line_index < len(lines):
        print("Reading line:", line_index, ":", lines[line_index])
        par_type = positionalParameters[line_index].parType
        word = lines[line_index].split()[0]
        if par_type == bool:
            value = custom_bool_cast(word)
        else:
            value = par_type(word)
        param.append(value)
        line_index += 1
    ok = line_index == len(positionalParameters)
    if not ok:
        print("ERROR: Insufficient number of values found in "
              "configuration file.")
        exit()
    var_names = [par.name for par in positionalParameters]
    par = collections.OrderedDict(zip(var_names, param))
    
    # Read named parameters
    tests = []
    testDict = dict()
    for i in range(line_index, len(lines)):
        line = lines[i].split("=")
        line = [x.strip() for x in line]
        try:
            key, values = line
        except ValueError:
            print("ERROR: unable to parse line: '", line, "'")
            raise

        if key not in namedParameters:
            namedParameters[key] = Parameter(key, values, "", str, False)
        else:
            namedParameters[key].value = values

        if key == "tests":
            tests = values.split(",")
            tests = [x.strip() for x in tests]
        elif key == 'ignored_tags':
            ignored_tags = values.split(",")
            ignored_tags = set([x.strip() for x in ignored_tags])
        else:
            if len(testDict) == 0:
                namedParameters[key].exp = img_exp
            testDict[key] = values.split(",")
            testDict[key] = [x.strip() for x in testDict[key]]
    # sliding_window = [0] * par['trials_in_block']

    # Reading parameters from the new animal configuration file
    print("Reading animal params file:", ANIMAL_PARAMS_FILE, flush=True)
    params_dict = dict()
    for par_config in ANIMAL_PARAMS:
        params_dict[par_config[PAR_KEY]] = par_config
    for par_config in GLOBAL_PARAMS:
        params_dict[par_config[PAR_KEY]] = par_config
    try:
        with open(ANIMAL_PARAMS_FILE, 'r') as pFile:
            raw_lines = pFile.readlines()  # read lines
            pFile.close()

        # Remove comments and empty lines from lines
        lines = []
        for line in raw_lines:
            line = line.strip()
            if len(line) == 0:
                continue
            if line[0] == "#":
                continue
            lines.append(line)

        init_global_par()
        for line in lines:
            split_line = line.split(" ")
            if len(split_line) == 2:
                animal, param = split_line
                value = ""
            else:
                animal, param, value = split_line
            if animal not in animalDict:
                animalDict[animal] = dict()
            if param in params_dict:
                par_config = params_dict[param]
                if par_config[PAR_RESET]:
                    value = par_config[PAR_INIT]
                elif par_config[PAR_TYPE] == int:
                    value = int(value)
                elif par_config[PAR_TYPE] == str:
                    value = value.strip()
                elif par_config[PAR_TYPE] == list:
                    value_list = value.split(",")
                    value = [x.strip() for x in value_list]
                elif par_config[PAR_TYPE] == "int_list":
                    if value.strip() == '':
                        value = [0] * par['trials_in_block']
                    else:
                        value_list = value.split(",")
                        value = [int(x.strip()) for x in value_list]
                else:
                    raise ValueError("Unknown data type:", par_config[PAR_TYPE])
            else:
                print("WARNING: Unknown parameter '" + str(param) + "' found.")
            animalDict[animal][param] = value
    except FileNotFoundError:
        print("Animal param file not found:", ANIMAL_PARAMS_FILE,
              "Loading fresh parameters instead.", flush=True)
        init_global_par()
    return par

    
def feed_it():
    """
    Turn motor to administer food.
    """
    print("feeding")
    increment_global_par('rew_cnt')
    GPIO.output(PIN_MOTOR_RIGHT, 0)
    GPIO.output(PIN_MOTOR_LEFT, 1)  # Turn left
    while GPIO.input(PIN_MOTOR_SNAP) == 0:  # wait for switch
        time.sleep(0.1)
    while GPIO.input(PIN_MOTOR_SNAP) == 1:  # wait for switch
        time.sleep(0.05)
    GPIO.output(PIN_MOTOR_RIGHT, 0)
    GPIO.output(PIN_MOTOR_LEFT, 0)


def get_results_file_name():
    return DATA_DIR + "/" + DATA_FILE


def get_animal_results_file_name(local_animal_id):
    return DATA_DIR + "/" + local_animal_id + "_" + DATA_FILE


def get_results_header():
    return '#' + ','.join(HEADER) + '\n'


def write_results_header(filename):
    # Determine state of the current file
    file_exists = True
    file_has_header = False
    file_has_correct_header = False
    lines = []
    try:
        with open(filename, 'r') as results_file:
            lines = results_file.readlines()
            if len(lines) > 0:
                first_line = lines[0]
                if len(first_line) > 0:
                    if first_line[0] == '#':
                        file_has_header = True
                        if first_line == get_results_header():
                            file_has_correct_header = True
    except IOError:
        file_exists = False

    # Determine what needs to be written to the current file, if anything
    if file_has_correct_header:
        return
    if file_exists:
        if file_has_header:
            lines[0] = get_results_header()
        else:
            lines = [get_results_header()] + lines
    else:
        lines = [get_results_header()]

    # Actually write to the current file
    with open(filename, 'w') as results_file:
        results_file.writelines(lines)

    
def log_it(local_animal_id, event, time1, time2, local_push, correct):
    print("LOGGING...")          
    # Build a data line and write it to memory
    if local_push in PUSH_DICT:
        local_push = PUSH_DICT[local_push]
    else:
        local_push = 'NA'
    if correct in PUSH_DICT:
        correct = PUSH_DICT[correct]
    else:
        correct = 'NA'
    d_list = [local_animal_id, event, time1, time2,
              get_animal_par('push_cnt_e'),
              get_animal_par('curr_test'),
              get_animal_par('curr_block'),
              get_animal_par('trial_cnt'),
              get_animal_par('failed_curr_trial'),
              get_animal_par('failed_trials'),
              get_animal_par('failed_blocks'), leds, local_push, correct,
              get_global_par('rew_cnt'),
              sum(get_animal_par('sliding_window')),
              ]
    # transform list into a comma delineates string of values
    d_line = ','.join(map(str, d_list))
    # open for appending  
    data_text = open(get_animal_results_file_name(local_animal_id), 'a')
    data_text.write(d_line + "\n")
    data_text.close()
    data_text_f = open(get_results_file_name(), 'a')
    data_text_f.write(d_line + "\n")
    data_text_f.close()
    print("LOGGING DONE")


def log_error():
    print("WRITING ERROR LOG...")          
    data_text = open(ERROR_LOG, 'w')
    data_text.write(traceback.format_exc())
    data_text.close()
    print("WRITING ERROR LOG DONE")

    
def on_animal_leave():
    global oldTag
    global push    
    global listen
    global animal_id
    write_param()
    oldTag = RfidTag()
    listen = 0
    push = "D"
    animal_id = None
    return False


def button_pressed():
    """
    Checks if a button has been pressed.

    Note: only works if listen is set to 1.

    :return: True if a button has been pressed, False otherwise.
    """
    global listen
    if push != 0:
        listen = 0
        return True
    else:
        return False


def animal_present():
    """
    Checks if the animal is still present.

    :return: True if the current animal is still there, False otherwise.
    """
    global oldTag
    global push
    global listen
    global animal_last_seen

    # Otherwise, check if the animal is still present
    tag = read_rfid()
    local_animal_id = tag.tag_number
    if local_animal_id is None:
        print("ERROR: AnimalId is set to None")
        # TODO: This case really shouldn't happen, maybe throw an exception?
        return False

    elif local_animal_id != animal_id:
        # TODO: We are picking up a different raccoon from the one with which
        # we started the trial. Need to find some resolution
        if PRINT_TIME:
            print("Detected another tag")
            print("Now:", now(), "Time from tag:", animal_last_seen)
        if now() - animal_last_seen > sec(par['rfid_new_animal_timeout']):
            # We haven't seen the animal for a while now, terminate the test
            print("We are seeing a different animal for a while, switching...")
            return False
        if reliable:
            print("We are seeing a different animal and sensor readings appear "
                  "reliable, switching...")
            return False
    else:
        # The same raccoon is still there, we are good
        animal_last_seen = tag.tag_time_stamp
        if PRINT_TIME:
            print("Detected the same tag")
            print("Now:", now(), "Time from tag:", animal_last_seen)
        if now() - animal_last_seen > sec(par['rfid_timeout']):
            print("We haven't seen the animal for a while now, "
                  "terminate the test")
            # We haven't seen the animal for a while now, terminate the test
            return False

    # JH: Lines added for animation
    time.sleep(0.02)
    return True

    
# JH: Breaking the push wait into different functions, so I can use them
# elsewhere
def push_init():
    global push
    global listen
    push = 0
    time.sleep(0.05)  # sensor warm up
    listen = 1  # respond to button push interrupts


def push_poll():
    global push
    if button_pressed():
        return False
    if not animal_present():
        push = "D"
        return False
    return True


# Monitor buttons and presence/absence
def push_wait():
    push_init()
    while push_poll():
        pass  # this will monitor IR senor and the buttons
    print("push = ", push)


def timeout(length):
    """
    Timeout that happens when a raccoon fails one of the trials. While in
    timeout, the system won't respond to the raccoon using the touch screen, but
    it will record when the Raccoon leaves the touch screen. Once the raccoon
    has left the touch screen, the device won't respond or record raccoons
    entering or leaving the system until the timeout is over.
    """
    global oldTag
    global push
    global timeoutState
    global animal_last_seen
    timeoutState = "started"
    time_start = now().strftime(LOG_TIME_FORMAT)
    print("Starting timeout of:", length, "seconds.")
    pygame.event.pump()
    for t in range(length):
        time.sleep(1)
        # Once push is set to X, we no longer monitor the animal.
        # We just wait until the timeout is over.
        if push == "X":
            pass
        elif not animal_present():
            # We record the time at which the animal left, but otherwise, the
            # timeout will not be responsible for resetting parameters; this
            # should be done by the function calling the timeout.
            time_end = now().strftime(LOG_TIME_FORMAT)
            log_it(animal_id, "Departed_during_timeout", time_start, time_end, "NA", "NA")
            # Stop listing to input
            push = "X"

        pygame.event.pump()
    timeoutState = "stopped"
    

# JH: Changed how parameters are written
def write_current_params():
    with open(CONFIG_FILE, 'w') as pFile:
        for local_par in positionalParameters:
            if isinstance(local_par.value, int):
                pFile.write(str(local_par.value).zfill(3))
            else:
                pFile.write(str(local_par.value))
            pFile.write(" ")
            pFile.write(local_par.exp)
            pFile.write("\n")
        for local_par in namedParameters.values():
            if len(local_par.exp) > 0:
                pFile.write("\n")
                for line in local_par.exp.split("\n"):
                    pFile.write("# ")
                    pFile.write(line)
                    pFile.write("\n")
            pFile.write(local_par.name)
            pFile.write("=")
            pFile.write(local_par.value)
            pFile.write("\n")
    with open(ANIMAL_PARAMS_FILE, 'w') as pFile:
        for animal in animalDict:
            for param in animalDict[animal]:
                pFile.write(animal + " ")
                pFile.write(param + " ")
                if isinstance(animalDict[animal][param], list):
                    str_list = [str(p) for p in animalDict[animal][param]]
                    pFile.write(",".join(str_list) + "\n")
                else:
                    pFile.write(str(animalDict[animal][param]) + "\n")
                 

# JH: Changed how parameters are written
def write_param():
    for posPar, value in zip(positionalParameters, par.values()):
        posPar.value = value
    write_current_params()


def cleanup():
    print("Cleanup")
    leds.turn_both_off()
    pygame.quit()
    GPIO.remove_event_detect(PIN_JOY_LEFT)
    GPIO.remove_event_detect(PIN_JOY_RIGHT)
    GPIO.cleanup()


def wait_for_animal():
    global push
    global animal_id
    global animal_last_seen
    quit_game = 0

    tag = read_rfid()
    local_animal_id = tag.tag_number
    while local_animal_id is None and quit_game == 0:
        # print("no animal")
        tag = read_rfid()
        local_animal_id = tag.tag_number
        for event in pygame.event.get():
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    # If a keyboard input is detected, then set the flag to
                    # quit the game
                    quit_game = 1
        time.sleep(.5)
    animal_id = local_animal_id
    init_animal_par(animal_id)
    animal_last_seen = tag.tag_time_stamp
        
    if quit_game == 0:
        print("animal detected")
        time_now = now()
        # subtract 12 hours when defining the day
        # day_now = time_now - datetime.timedelta(hours=12)
        # day_now = day_now.day
        time_start = time_now.strftime(LOG_TIME_FORMAT)
        print("Start time: " + time_start)
        push = "X"
        # print("parameters read")
        # print(time_start)
        # Check if we are starting a new day
        # if day_now != par['rew_day']:
        #     # This line is necessary - updates day variable.
        #     par['rew_day'] = day_now
        #     set_global_par('rew_cnt', 0)
    return quit_game


def entry_reward():
    global push
    # Feed immediately if there are entry rewards remaining and it's a new entry
    if par['entry_reward'] > get_animal_par('entry_cnt') and push == "X":
        feed_it()
        print("Providing entry reward")
        increment_animal_par('entry_cnt')
        time_start = now().strftime(LOG_TIME_FORMAT)
        log_it(animal_id, "Entry", time_start, time_start, "NA", "NA")
        push = "E"
        time.sleep(1)


def training():
    global push
    print("Training mode...")
    # get the time of initial detection
    time_start = now().strftime(LOG_TIME_FORMAT)
    entry_reward()
        
    if par['push_reward_e'] > get_animal_par('push_cnt_e'):
        leds.turn_both_on()
        total_side_reward = par['push_reward_r'] + par['push_reward_l']
        either_reward = par['push_reward_e'] - total_side_reward
        either_claimed = (get_animal_par('push_cnt_e') -
                          get_animal_par('push_cnt_r') -
                          get_animal_par('push_cnt_l'))

        # wait for button push or animal departure
        push_wait()
        # get the time of initial detection     
        time_end = now().strftime(LOG_TIME_FORMAT)
        if push != "D":
            if push == "R":
                increment_animal_par('train_push_cnt_r')
                if par['push_reward_r'] > get_animal_par('push_cnt_r'):
                    feed_it()
                    print("reward R")
                    increment_animal_par('push_cnt_e')
                    increment_animal_par('push_cnt_r')
                    log_it(animal_id, "Training_push_right", time_start, time_end, push, "NA")
                elif either_claimed < either_reward:
                    feed_it()
                    print("reward E")
                    increment_animal_par('push_cnt_e')
                    log_it(animal_id, "Training_push_either", time_start, time_end, push, "NA")
                else:
                    print("No more rewards for this side...")
                    log_it(animal_id, "Training_push_no_reward", time_start, time_end, push, "NA")
            elif push == "L":
                increment_animal_par('train_push_cnt_l')
                if par['push_reward_l'] > get_animal_par('push_cnt_l'):
                    feed_it()
                    print("reward L")
                    increment_animal_par('push_cnt_e')
                    increment_animal_par('push_cnt_l')
                    log_it(animal_id, "Training_push_left", time_start, time_end, push, "NA")
                elif either_claimed < either_reward:
                    feed_it()
                    print("reward E")
                    increment_animal_par('push_cnt_e')
                    log_it(animal_id, "Training_push_either", time_start, time_end, push, "NA")
                else:
                    print("No more rewards for this side...")
                    log_it(animal_id, "Training_push_no_reward", time_start, time_end, push, "NA")
        else:
            # log animal departed
            log_it(animal_id, "Departed", time_start, time_end, "NA", "NA")
            on_animal_leave()
    elif par['entry_reward'] <= get_animal_par('entry_cnt'):
        set_animal_par('curr_test', 1)
        set_animal_par('sliding_window', [0] * par['trials_in_block'])
    else:
        # Set push to X so the animal can gain an additional entry reward
        # without having to leave first.
        push = "X"


def end_block():
    # global sliding_window
    print("Block ended")
    set_animal_par('trial_cnt', 0)
    increment_animal_par('curr_block')
    set_animal_par('failed_trials', 0)
    set_animal_par('trial_suc_cnt', 0)
    set_animal_par('sliding_window', [0] * par['trials_in_block'])
    # sliding_window = [0] * par['trials_in_block']
    

def block_success():
    print("Block was successful")
    increment_animal_par('block_suc_cnt')
    if get_animal_par('block_suc_cnt') >= par['blocks_to_pass']:
        # Test successfull
        increment_animal_par('curr_test')
        increment_animal_par('tests_current_session')
        set_animal_par('block_suc_cnt', 0)
        if get_animal_par('curr_test') > len(tests) and par['loop_test'] > 0:
            set_animal_par('curr_test', par['loop_test'])
        if int(par['between_test_timeout']) > 0:
            timeout(int(par['between_test_timeout']))


def block_fail():
    print("Block failed")
    set_animal_par('failed_blocks', get_animal_par('failed_blocks') + 1)
    test_failure = get_animal_par('failed_blocks') >= par['max_failed_blocks']
    failed_blocks_timeout_active = par['max_failed_blocks'] > 0
    if test_failure and failed_blocks_timeout_active:
        leds.turn_both_off()
        timeout(int(par['failed_blocks_timeout']*60))
        set_animal_par('failed_blocks', 0)
        play_sound("beep_hi.wav")

        
def animal_has_tests_left():
    tests_left = get_animal_par('curr_test') <= len(tests)
    if par['max_tests_session'] != 0:
        ses = get_animal_par('tests_current_session') < par['max_tests_session']
    else:
        ses = True
    return tests_left and ses
        
        
def testing():
    print("Testing mode...")
    entry_reward()
    test_index = get_animal_par('curr_test')
    trial_count = get_animal_par('trial_cnt')
    
    if not animal_has_tests_left() or test_index == 0:
        return
    # subtract 1 because the count starts with zero
    test = tests[test_index-1]
    if test.startswith("random"):
        # choose an image from the list at random
        answer = random.choice(testDict[test]) 
    elif test.startswith("shuffle"):
        prev_shuffle = get_global_par("previous_shuffle")
        print("Shuffled tests list:", prev_shuffle)
        at_end_of_trials = trial_count % len(testDict[test]) == 0
        current_trial_not_failed = get_animal_par('failed_curr_trial') == 0
        reshuffle = at_end_of_trials and current_trial_not_failed
        if reshuffle or len(prev_shuffle) == 0:
            print("Shuffling tests")
            shuffled_tests = testDict[test]
            random.shuffle(shuffled_tests)
            answer = shuffled_tests[0]
            set_global_par("previous_shuffle", shuffled_tests)
        else:
            print("Selecting next image")
            answer = prev_shuffle[trial_count % len(prev_shuffle)]
    else:
        list_of_ans = testDict[test]
        answer = list_of_ans[get_animal_par('trial_cnt') % len(list_of_ans)]
    answer, led_config = answer.split('-')

    # Initialize animal preference if not set
    if get_animal_par("preference_answer") == "X":
        push_r = get_animal_par('train_push_cnt_r')
        push_l = get_animal_par('train_push_cnt_l')
        if push_r > push_l:
            set_animal_par("preference_answer", "R")
        elif push_l > push_r:
            set_animal_par("preference_answer", "L")
        elif random.random() < 0.5:
            set_animal_par("preference_answer", "R")
        else:
            set_animal_par("preference_answer", "L")

    if answer == "S":
        answer = get_animal_par("preference_answer")
        print("Test:", test, "same as preference (S); preference:",
              get_animal_par("preference_answer"), "answer:", answer)
    elif answer == "O":
        answer = OPPOSITE_ANSWERS[get_animal_par("preference_answer")]
        print("Test:", test, "opposite from preference (O); preference:",
              get_animal_par("preference_answer"), "answer:", answer)
    else:
        print("Test:", test, " ", answer)

    # Get the time of initial detection
    leds.set_leds(led_config)
    time_start = now().strftime(LOG_TIME_FORMAT)
    push_wait()  # Wait for button push or animal departure
    # Get the time of initial detection
    time_end = now().strftime(LOG_TIME_FORMAT)
    if push != "D":  # Animal pushed a button
        if push == answer or answer == "E" or answer == "I":
            # If the animal got it right..
            feed_it()
            print("test reward")
            increment_animal_par('trial_suc_cnt')
            set_animal_par('failed_curr_trial', 0)
            get_animal_par('sliding_window')[get_trial_index()] = 1
            log_it(animal_id, "Success", time_start, time_end, push, answer)
            if answer == "I":
                set_animal_par("preference_answer", push)
        elif push != answer:
            print("wrong. test failed", flush=True)
            play_sound("beep_low.wav")
            increment_animal_par('failed_trials')
            increment_animal_par('failed_curr_trial')
            get_animal_par('sliding_window')[get_trial_index()] = 0
            log_it(animal_id, "Failure", time_start, time_end, push, answer)
            # Change to monitor departure.
            leds.turn_both_off()
            if par['fail_trial_repeat'] >= get_animal_par('failed_curr_trial'):
                set_animal_par('trial_cnt', get_animal_par('trial_cnt') - 1)
            else:
                set_animal_par('failed_curr_trial', 0)
            fail = get_animal_par('failed_trials') >= par['max_failed_trails']
            failed_trials_timeout_active = par['max_failed_trails'] > 0
            timeout(par['fail_delay'])
            if fail and failed_trials_timeout_active:
                timeout(par['failed_trails_timeout'])
                set_animal_par('failed_trials', 0)
                play_sound("beep_hi.wav")
        # JH: Trial count should be updated after logging, so the
        # correct number is logged
        increment_animal_par('trial_cnt')
        if par["consecutive_block"]:
            if sum(get_animal_par('sliding_window')) >= par['block_suc_thresh']:
                block_success()
                end_block()
        elif get_animal_par('trial_cnt') >= par['trials_in_block']:
            if get_animal_par('trial_suc_cnt') >= par['block_suc_thresh']:
                block_success()
            else:
                block_fail()
            end_block()
                  
    else:  # Animal departed
        # log data for entry reward
        log_it(animal_id, "Departed", time_start, time_end, "NA", "NA")
        on_animal_leave()


def on_out_of_food():
    leds.turn_both_off()
    while True:
        if get_global_par('rew_cnt') >= par['rew_max']:
            print("Out of reward, waiting for animal to leave...", flush=True)
        elif not animal_has_tests_left():
            print("Animal finished all tests, "
                  "waiting for animal to leave...", flush=True)
        # get the time of initial detection
        time_start = now().strftime(LOG_TIME_FORMAT)
        push_wait()  # wait for button push or animal departure
        time_end = now().strftime(LOG_TIME_FORMAT)
        if push == "D":
            log_it(animal_id, "Departed", time_start, time_end, "NA", "NA")
            on_animal_leave()
            break      # break infinite loop if animal has left.
        play_sound("beep_low.wav")
        # log animal pushing button while device in timeout
        log_it(animal_id, "Push_while_out_of_food", time_start, time_end, push, "NA")
    write_param()


def wait_for_animal_to_leave():
    global push
    time_start = now().strftime(LOG_TIME_FORMAT)
    while animal_present():
        time.sleep(1)
    time_end = now().strftime(LOG_TIME_FORMAT)
    log_it(animal_id, "Departed", time_start, time_end, "NA", "NA")
    on_animal_leave()

# =========== MAIN PROGRAM ========= #

def main():
    # Declare global variables
    global screen

    # Signal to the RFID reader that it should send its output to the RPi.
    connected = False
    while not connected:
        print("Sending CTL1 to scanner.", flush=True)
        ard.write("CTL1\r".encode())
        connected = True
        time_waited = 0
        while ard.inWaiting() == 0:
            print("Waiting for scanner to respond...", flush=True)
            time.sleep(1)
            time_waited += 1
            # If the scanner does not respond in 5 seconds, assume that it is in
            # dual reader mode. Try sending the Ctrl-QUIT command and try again.
            if time_waited > 5:
                connected = False
                print("Scanner took too long to respond. Sending Ctrl-QUIT in an "
                      "attempt to exit dual reader mode...", flush=True)
                ard.write(CTRL_QUIT.encode())
                time_waited = 0
                while ard.inWaiting() == 0:
                    print("Waiting for scanner to respond...", flush=True)
                    time.sleep(1)
                    time_waited += 1
                    if time_waited > 10:
                        print("Connection timed-out, aborting...")
                        exit()
                response = ard.readline().decode()
                print("Response received:", response)
                if response == 'LOGGER: Dual-Reader Data Collection Disabled':
                    print("Successfully stopped dual-reader collection")
    print("Writing to serial command received:", ard.readline().decode())
    print("Connection assumed to be successfull") 

    # Setup GPIO interface to feeder, IR, etc.
    GPIO.setmode(GPIO.BCM)
    # Input for motor snap switch. requires pull up enabled 
    GPIO.setup(PIN_MOTOR_SNAP, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    # Motor control - set high to turn motor right (facing spindle)
    GPIO.setup(PIN_MOTOR_RIGHT, GPIO.OUT)
    # Motor control - set high to turn motor left (facing spindle)
    GPIO.setup(PIN_MOTOR_LEFT, GPIO.OUT)
    # Input for right screen button. requires pull up enabled 
    GPIO.setup(PIN_JOY_RIGHT, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    # Input for left screen button. requires pull up enabled
    GPIO.setup(PIN_JOY_LEFT, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    # Output for the right LED
    GPIO.setup(PIN_LED_RIGHT, GPIO.OUT)
    # Output for the left LED
    GPIO.setup(PIN_LED_LEFT, GPIO.OUT)

    # motor in standby
    GPIO.output(PIN_MOTOR_RIGHT, 0)
    # motor in standby
    GPIO.output(PIN_MOTOR_LEFT, 0)
    
    # Set up interrupts for when we are listening for button pushes on the
    # monitor
    GPIO.add_event_detect(PIN_JOY_LEFT,
                          GPIO.FALLING,
                          callback=pushed,
                          bouncetime=500)
    GPIO.add_event_detect(PIN_JOY_RIGHT,
                          GPIO.FALLING,
                          callback=pushed,
                          bouncetime=500)
    
    # Start Pygame
    # Trade off between speed and fidelity here
    pygame.mixer.pre_init(22050, -16, 1, 1024) 
    pygame.mixer.init()
    pygame.display.init()
    if MODE != "fullscreen":    
        screen = pygame.display.set_mode((1280, 768))
    else:
        screen = pygame.display.set_mode((1280, 768), pygame.FULLSCREEN)

    # JH: While the current code is designed for working with LEDs, rather than
    # a screen, we'll show an empty screen so we can interface with pygame.
    show_img("black.jpg")
    leds.turn_both_on()

    # initialize parameters, just to avoid 'par not defined' errors
    get_params()

    write_results_header(get_results_file_name())

    # Used as a flag to signal a keystroke--which stops the program
    quit_game = 0
    while quit_game == 0:
        # If there is no animal, wait for an animal
        if push == "D":
            # We turn the LEDs on while waiting for an animal
            leds.turn_both_on()
            quit_game = wait_for_animal()
        elif animal_id in ignored_tags:
            print('Current animal is ignored, '
                  'waiting for animal to leave...')
            # We turn the LEDs off while waiting for an animal to leave
            leds.turn_both_off()
            wait_for_animal_to_leave()
        elif not animal_has_tests_left():
            print('Current animal finished all its tests, '
                  'waiting for animal to leave...')
            # We turn the LEDs off while waiting for an animal to leave
            leds.turn_both_off()
            wait_for_animal_to_leave()
        elif get_global_par('rew_cnt') < par['rew_max']:
            # Training mode - not testing yet
            if get_animal_par('curr_test') == 0:
                training()
            else:  # Testing mode
                testing()                
        else:  # do the following if the reward maximum has been reached
            on_out_of_food()
    cleanup()


# ============== SETUP ============== #

# Global variables

# JH: Used for interacting with the touch screen.
# They are defined global because they are used in a callback function
listen = 0

# Indicates animal not present (D = departed)
push = "D"
leds = LEDS()

# JH: Field only for the purpose of debugging
timeoutState = "stopped"

# JH: Parameter variables. Made global as it is a pain to pass them to every
# functions separately
positionalParameters = []
namedParameters = collections.OrderedDict()
par = None
screen = None

# The size of the sliding window for the consecutive block experiment
# sliding_window = []

# JH: For the purpose of the RFID reader
port = "/dev/ttyS0"
ard = serial.Serial(port, 115200, timeout=5)

animal_id = None
animal_last_seen = None
oldTag = RfidTag()
animalDict = dict()
reliable = True
last_time_since_unreliable = now()
animals_seen_this_session = set()

# JH: General good practice; allows this file to be imported without running it
if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        cleanup()
    except KeyboardInterrupt:
        cleanup()
    except Exception as err:
        # JH: perform cleanup (and close the screen) if the program crashes
        if err.args[0] == "exit request":
            cleanup()
        else:
            log_error()
            cleanup()
            raise
