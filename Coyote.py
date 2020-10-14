# Puzzle box control system
__version__="v4 06-28-2018"
__author__="E. Bridge and J. Huizinga"
#Licensed in the public domain#

# Constants
ID = "1031"
MODE = "window" # set this to "fullscreen" to enable fullscreen
FRAME_TIME=50   # Aim for 20 frames per second

# JH: I don't think absolute paths are necessary on the Rasberry Pi, meaning
# these paths should work, regarless of where the code is run. Please change
# back to absolute paths if this doesn't work.
FOLDER="/media/pi/RACCOON11/"
CONFIG_FILE="/media/pi/RACCOON11/COYConfigurationFile.txt"
#CONFIG_FILE="exampleExtraTests.txt"
#CONFIG_FILE="exampleFailedBlockDelay.txt"
#CONFIG_FILE="exampleFailedTrialDelay.txt"
#CONFIG_FILE="exampleTrajectory.txt"
DATA_FILE="/media/pi/RACCOON11/06282018_COY1031P.txt"
ERROR_LOG="/media/pi/RACCOON11/06282018_errorP.txt"
# FOLDER="/media/pi/RACCOON5/"
# CONFIG_FILE="/media/pi/RACCOON5/animationsRAC129.txt"
# DATA_FILE="/media/pi/RACCOON5/RAC129Results.txt"
# ERROR_LOG="/media/pi/RACCOON5/error.txt"

# Pin numbers
PIN_REMOTE_IN=18
PIN_MOTOR_SNAP=20
PIN_MOTOR_RIGHT=13
PIN_MOTOR_LEFT=19
PIN_JOY_RIGHT=6
PIN_JOY_LEFT=5
PIN_LED_RIGHT=27
PIN_LED_LEFT=17

# Import necessary libraries
import subprocess, tempfile # For getting the time
import pygame               # For full screen and sound
import RPi.GPIO as GPIO     # Input output pin controls
import time                 # For delays
import datetime             # For processing time stamps
import collections          # Needed for making an ordered dictionary
import random               # For randomization and shuffling
import os                   # For interacting with the filesystem
import sys                  # For checking the operating system
import traceback            # For logging when the program crashes
import threading            # For locking the feeding process

# JH: Class for keeping track of the LED status
class LEDS:
    def __init__(self):
        self.left=False
        self.right=False

        
    def turnLeftOn(self):
        self.left=True
        GPIO.output(PIN_LED_LEFT, 1)

        
    def turnRightOn(self):
        self.right=True
        GPIO.output(PIN_LED_RIGHT, 1)

        
    def turnLeftOff(self):
        self.left=False
        GPIO.output(PIN_LED_LEFT, 0)

        
    def turnRightOff(self):
        self.right=False
        GPIO.output(PIN_LED_RIGHT, 0)


    def turnBothOn(self):
        self.turnLeftOn()
        self.turnRightOn()


    def turnBothOff(self):
        self.turnLeftOff()
        self.turnRightOff()


    def setLEDs(self, setting):
        if setting == "L":
            self.turnLeftOn()
            self.turnRightOff()
        elif setting == "R":
            self.turnRightOn()
            self.turnLeftOff()
        elif setting == "E" or setting == "B":
            self.turnBothOn()
        elif setting == "N":
            self.turnBothOff()
            
            
    def __str__(self):
        result="Left: "
        if self.left:
            result+="On"
        else:
            result+="Off"
        result+=" Right: "
        if self.right:
            result+="On"
        else:
            result+="Off"
        return result
    

# JH: Class added for reading parameters
class Parameter:
    def __init__(self, name, default, exp, parType, positional):
        self.name = name
        self.default = default
        self.exp = exp
        self.positional = positional
        self.value = default
        self.parType = parType


######################### SETUP ###############################

OPPOSITE_ANSWERS={"R":"L", "L":"R", "X":"X"}
LEGAL_ANSWERS=["L", "R", "E", "I"]

# Global variables

# JH: Used for interacting with the touch screen.
# They are defined global because they are used in a callback function
listen = 0
push = None
prev_push = None
p = None
leds=LEDS()

# JH: Field only for the purpose of debuggin
timeoutState="stopped"

# JH: Parameter variables. Made global as it is a pain to pass them to every
# functions separately
positionalParameters = []
namedParameters = collections.OrderedDict()
par = None
screen=None

# The size of the sliding window for the consecutive block experiment
slidingWindow=None
prevAnswer = "X"
lastFed = None
isFeeding = False
feedingLock = threading.Lock()
endOfLastFeed = datetime.datetime.now()
timeLastPush = datetime.datetime.now()
minimumFeedingInterval = datetime.timedelta(seconds=0.5)


######################## FUNCTIONS #################################    

def pushed(channel): #interrupt detection function
    global listen    
    global push
    global prev_push
    prev_push=push
    # If we are already feeding, ignore this button press
    if isFeeding:
        print("trigger detected, but device is feeding...", flush = True)
        return
    if datetime.datetime.now() - endOfLastFeed < minimumFeedingInterval:
        print("trigger detected, but last feed was too recent.", flush = True)
        return
    if listen == 1: #Only do the following if we are listening...
        print("trigger detected...", flush = True)        
        if(channel==PIN_JOY_LEFT):
            #time.sleep(0.01)            
            #if GPIO.input(PIN_JOY_LEFT) == 0: #make sure it's a push and not a release
            push = "L"
            listen = 0 #turn off listening for interrupts        
            #print("Left button pushed " + push)
        if(channel==PIN_JOY_RIGHT):
            #time.sleep(0.01)            
            #if GPIO.input(PIN_JOY_RIGHT) == 0: #make sure it's a push and not a release            
            push = "R"
            listen = 0 #turn off listening for interrupts        
            #print("Right button pushed " + push)


def remote(channel):
    print("Remote button press registered.")
    if GPIO.input(PIN_REMOTE_IN) == 1:
        feedIt()


def showImg(img): #Show an image full screen (or not full screen)
    global screen
    img1 = pygame.image.load(FOLDER + img)
    screen.blit(img1, (0,0))
    pygame.display.flip()
    pygame.event.pump()


def customBoolCast(string):
    if string.lower() == "false":
        return False
    elif string == "0":
        return False
    else:
        return bool(string)
    
def playSound(wav):
    wavFile = FOLDER + wav 
    beep = pygame.mixer.Sound(wavFile)
    beep.play()

    
# JH: Code for new parameters  
def resetParams():
    global positionalParameters
    global namedParameters
    positionalParameters = []
    namedParameters = collections.OrderedDict()

    
# JH: Code for new parameters
def addParam(name, default, exp, parType=int):
    positionalParameters.append(Parameter(name, default, exp, parType, True))

    
# JH: More code for new parameters
def addNamedParam(name, default, exp, parType=str):
    namedParameters[name] = Parameter(name, default, exp, parType, False)

    
def getParams():  #open the parameters file and get data
    global par  
    global tests
    global testDict
    global slidingWindow

    resetParams()
    addParam("entry_reward", 2, "Maximum entry rewards")
    addParam("push_reward_e", 4,
             "Maximum screen push rewards (total of both sides)")
    addParam("push_reward_r", 2,
             "Maximum screen push rewards for the right side")
    addParam("push_reward_l", 2,
             "Maximum screen push rewards for the left side")
    addParam("trials_in_block", 12, "Number of trials in a block")
    addParam("loop_test", 0,
             "Which test to loop back to after all are complete")
    addParam("block_suc_thresh", 9,
             "Block success threshold - minimum number of trials passed to move on")
    addParam("blocks_to_pass", 2,
             "Number of successive successful blocks to move to the next test")
    addParam("entry_cnt", 0, "Entry count")
    addParam("push_cnt_e", 0, "Screen push count - total for both sides")
    addParam("push_cnt_r", 0, "Screen push count - right side")
    addParam("push_cnt_l", 0, "Screen push count - left side")
    addParam("trial_cnt", 0, "Trial count for the current block")
    addParam("trial_suc_cnt", 0, "Successful trial count for the current block")
    addParam("curr_block", 0, "Block count for current test")
    addParam("block_suc_cnt", 0, "Successful block count for the current test")
    addParam("curr_test", 0, "Current test")
    addParam("fail_delay", 5,
             "Fail delay - how many seconds to delay testing if an animal fails a trial")
    addParam("rew_cnt", 0,
             "Daily reward count - counts rewards given in a single day")
    addParam("rew_max", 50, "Maximum number of reward allowed in a day")
    addParam("rew_day", 1, "Day of the month ")
    addParam("max_failed_blocks", 0,
             "Number of times a block can be failed before a long timeout.")
    addParam("failed_blocks", 0,
             "Current number of failed blocks (handled by program).")
    addParam("reset_blocks", 0,
             "Current number of reset blocks (handled by program).")
    addParam("failed_blocks_timout", 30,
             "Timeout when the maximum number of failed blocks is reached in minutes.")
    addParam("max_failed_trails", 0,
             "Number of trails that can be failed before a timeout (resets every block).")
    addParam("failed_trails_timeout", 60,
             "Timeout when the maximum number of failed trials is reached in seconds.")
    addParam("fail_trial_repeat", 0,
             "Number of times trial is repeated when a wrong answer is given.")
    addParam("failed_current_trial", 0,
             "Wrong answers given on current trial (handled by program).")
    addParam("failed_trials", 0,
             "Wrong answers given in current block (handled by program).")
    addParam("consecutive_block", False,
             ": If set to True, enables consecutive block trails.", bool)
    addParam("feed_interval", 0,
             "Interval in minutes for periodic feeding (0 to disable periodic feeding).")
    addParam("reset_time", 60,
             "Time until the testing phase is reset in minutes.")
    addNamedParam("previous_shuffle", "",
                  "Order of trials stored from a previous experiment.\n"
                  "Handled automatically, so it does not need to be altered.")
    addNamedParam("tests", "shuffle1",
                  "The ordered sequence of tests to be performed. The answers\n"
                  "for each test should be defined on a separate line. For\n"
                  "example, if your test is named test1, you should define a\n"
                  "list of answers for that test as: test1=L-L, R-R\n"
                  "The special names \"rand,\"  and \"shuffle\"\n"
                  "can be used for random trial selection from the entire list.")
    imgExp=("The lists of trials associated with each test. Each trial is an\n"
            "answer-led pair, where the first character determines the correct\n"
            "answer (“R” for right, “L” for left, “E” for either, “I” for\n"
            "input, “S” for same as input, “O” opposite from input) and the\n"
            "second character determines which LEDs will be on (“R” for right,\n"
            "“L” for left, “B” for both, and “N” for neither).")
    addNamedParam("shuffle1", "L-L, R-R", imgExp)

    # Read the configuration file, or write a new configuration file if it could
    # not be found.
    print("Reading configuration file:", CONFIG_FILE, flush=True)
    try:
        with open(CONFIG_FILE, 'r') as pFile:
            raw_lines = pFile.readlines()  #read lines 
            pFile.close()
    except FileNotFoundError:
        print("ERROR: Configuration file", CONFIG_FILE, "not found.")
        print("Creating new configuration file.")
        print("Please check the configuration and restart.")
        writeCurrentParams()
        exit()

    # Remove the values for the example parameters; read them from file instead
    namedParameters["tests"].value=""
    del namedParameters["shuffle1"]
    
    # Remove comments and empty lines from lines
    lines=[]
    for line in raw_lines:
        line = line.strip()
        if len(line) == 0:
            continue
        if line[0] == "#":
            continue
        lines.append(line)

    # Read positional parameters
    param = []
    lineIndex=0
    while lineIndex < len(positionalParameters) and lineIndex < len(lines):
        print("Reading line:", lineIndex, ":", lines[lineIndex])
        parType = positionalParameters[lineIndex].parType
        word = lines[lineIndex].split()[0]
        if parType == bool:
            value=customBoolCast(word)
        else:
            value=parType(word)
        param.append(value)
        lineIndex+=1
    ok = lineIndex == len(positionalParameters)
    if not ok:
        print("ERROR: Insufficient number of values found in configuration file.")
        exit()
    varNames = [par.name for par in positionalParameters]
    par = collections.OrderedDict(zip(varNames, param))
    
    # Read named parameters
    par["previous_shuffle"] = []
    tests = []
    testDict = dict()
    for i in range(lineIndex, len(lines)):
        line = lines[i].split("=")
        line = [x.strip() for x in line]
        key, values = line

        if key not in namedParameters:
            namedParameters[key] = Parameter(key, values, "", str, False)
        else:
            namedParameters[key].value = values

        if key == "tests":
            tests = values.split(",")
            tests = [x.strip() for x in tests]
        elif key == "previous_shuffle":
            par["previous_shuffle"] = values.split(",")
            par["previous_shuffle"] = [x.strip() for x in par["previous_shuffle"]]
        else:
            if len(testDict) == 0:
                namedParameters[key].exp=imgExp
            testDict[key] = values.split(",")
            testDict[key] = [x.strip() for x in testDict[key]]
    slidingWindow=[0]*par['trials_in_block']
    return par

    
def feedIt():
    """
    Turn motor to administer food.
    """
    global isFeeding
    global endOfLastFeed
    feedingLock.acquire()
    if datetime.datetime.now() - endOfLastFeed < minimumFeedingInterval:
        print("Attempting to feed too quickly, ignore request.")
        feedingLock.release()
        return
    isFeeding = True
    print("feeding")
    GPIO.output(PIN_MOTOR_RIGHT,0) 
    GPIO.output(PIN_MOTOR_LEFT,1) #Turn left
    while GPIO.input(PIN_MOTOR_SNAP)== 0: #wait for switch
        time.sleep(0.1)
    while GPIO.input(PIN_MOTOR_SNAP) == 1: #wait for switch
        time.sleep(0.05)
    GPIO.output(PIN_MOTOR_RIGHT,0)
    GPIO.output(PIN_MOTOR_LEFT,0)
    isFeeding = False
    endOfLastFeed = datetime.datetime.now()
    feedingLock.release()

    
def logIt(AnimalID, event, time1, time2, push, correct): 
    print("LOGGING...")          
    global par
    #Build a data line and write it to memory
    dList = [AnimalID,event,time1,time2, par['curr_test'], par['curr_block'], 
             par['trial_cnt'], par['failed_current_trial'], par['failed_trials'],
             par['failed_blocks'], par['reset_blocks'], leds, push, correct, par['rew_cnt']]     
    global dLine         
    dLine  = ','.join(map(str, dList)) #transform list into a comma delinates string of values
    dataText = open(DATA_FILE, 'a')  #open for appending  
    dataText.write(dLine + "\n") 
    dataText.close()
    print("LOGGING DONE")


def logError(): 
    print("WRITING ERROR LOG...")          
    dataText = open(ERROR_LOG, 'w')  #open for appending  
    dataText.write(traceback.format_exc()) 
    dataText.close()
    print("WRITING ERROR LOG DONE")
    
    
# JH: Breaking the push wait into different functions, so I can use them elsewhere
def pushInit():
    print ("Waiting for button press")
    global push    
    global listen
    prev_push=push
    push = 0    
    listen = 1 #respond to button push interrupts


def timedFeed():
    global lastFed
    if par['feed_interval'] == 0:
        return
    feedInterval = datetime.timedelta(minutes=par['feed_interval'])
    if not lastFed:
        lastFed = datetime.datetime.now()
    elif datetime.datetime.now() - lastFed > feedInterval:
        feedIt()
        lastFed = datetime.datetime.now()

    
def pushPoll():
    #print ("Waiting for button press")
    # JH: This next line is not necessary in the real program, but it is
    # required for my testing scripts.
    GPIO.input(PIN_REMOTE_IN)
    if push != 0:
        return False
    time.sleep(0.02)
    return True

    
def pushExit():
    global listen
    listen = 0


def pushWait(): #Monitor buttons and presence/absence
    #print("push wait....", flush = True)
    global timeLastPush
    global push
    pushInit()
    reset_time = datetime.timedelta(minutes=par['reset_time'])
    while pushPoll():
        timedFeed()
        #print("Time since last push:", datetime.datetime.now() - timeLastPush,
        #      "reset_time:", reset_time) 
        if datetime.datetime.now() - timeLastPush > reset_time:
            # Timeout
            push = 'T'
            break
    timeLastPush = datetime.datetime.now()
    print("push = ", push)
    pushExit()


def timeout(length):
    """
    Timeout that happens when a Raccoon fails one of the trials. While in 
    timeout, the system won't respond to the Raccoon using the touch screen, but
    it will record when the Raccoon leaves the touch screen. Once the Raccoon 
    has left the touch screen, the device won't respond or record Raccoons 
    entering or leaving the system untill the timeout is over.
    """
    global push
    global timeoutState
    timeoutState="started"
    timeStart = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print("Starting timeout of:", length, "seconds.")
    pygame.event.pump()
    for t in range(length):
        time.sleep(1)
        pygame.event.pump()
    timeoutState="stopped"
    

# JH: Changed how parameters are written
def writeCurrentParams():
    with open(CONFIG_FILE, 'w') as pFile:
        for par in positionalParameters:
            if isinstance(par.value, int):
                pFile.write(str(par.value).zfill(3))
            else:
                pFile.write(str(par.value))
            pFile.write(" ")
            pFile.write(par.exp)
            pFile.write("\n")
        for par in namedParameters.values():
            if len(par.exp) > 0:
                pFile.write("\n")
                for line in par.exp.split("\n"):
                    pFile.write("# ")
                    pFile.write(line)
                    pFile.write("\n")
            pFile.write(par.name)
            pFile.write("=")
            pFile.write(par.value)
            pFile.write("\n")

            
# JH: Changed how parameters are written
def writeParam():
    for posPar, value in zip(positionalParameters, par.values()):
        posPar.value = value
        
    # Write the current shuffled list to a file
    shuffledStr = ""
    for i, image in enumerate(par["previous_shuffle"]):
        shuffledStr += image
        if i != len(par["previous_shuffle"]) - 1:
            shuffledStr += ","
    namedParameters["previous_shuffle"].value = shuffledStr

    writeCurrentParams()


def cleanup():
    print("Cleanup")
    leds.turnBothOff()
    pygame.quit()
    GPIO.remove_event_detect(PIN_JOY_LEFT)
    GPIO.remove_event_detect(PIN_JOY_RIGHT)
    GPIO.remove_event_detect(PIN_REMOTE_IN) 
    GPIO.cleanup()


def training():
    global push
    print("Training mode...")
    # get the time of initial detection
    timeStart = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
    if par['push_reward_e'] > par['push_cnt_e']:
        # JH: Turn on LEDs for which there is still reward remaining
        leds.turnBothOn()
        # if par['push_reward_r'] > par['push_cnt_r']:
        #    leds.turnRightOn()
        # if par['push_reward_l'] > par['push_cnt_l']:
        #    leds.turnLeftOn()
        either_reward = par['push_reward_e'] - par['push_reward_r'] - par['push_reward_l']
        either_claimed = par['push_cnt_e'] - par['push_cnt_r'] - par['push_cnt_l']
            
        pushWait() #wait for button push or animal departure
        # get the time of initial detection     
        timeEnd = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S') 
        if push != "D":
            if push == "R":
                if par['push_reward_r'] > par['push_cnt_r']:
                    feedIt()
                    print("reward R") 
                    par['push_cnt_e'] += 1  #advance count for entry rewards
                    par['rew_cnt'] += 1   #advance total daily reward count
                    par['push_cnt_r'] += 1 #advance right push count    
                    logIt(ID, "P", timeStart, timeEnd,push,"R") #log data for push reward
                elif either_claimed < either_reward:
                    feedIt()
                    print("reward E") 
                    par['push_cnt_e'] += 1
                    par['rew_cnt'] += 1
                    logIt(ID, "P", timeStart, timeEnd,push,"E") #log data for push reward
                else:
                    print("No more rewards for this side...")                            
                    logIt(ID, "X", timeStart, timeEnd,push,"L") #log data for failed  reward        
            elif push == "L":     
                if par['push_reward_l'] > par['push_cnt_l']:
                    feedIt()
                    print("reward L") 
                    par['push_cnt_e'] += 1  #advance count for entry rewards
                    par['rew_cnt'] += 1   #advance total daily reward count
                    par['push_cnt_l'] += 1 #advance right push count    
                    logIt(ID, "P", timeStart, timeEnd,push,"L") #log data for push reward
                elif either_claimed < either_reward:
                    feedIt()
                    print("reward E") 
                    par['push_cnt_e'] += 1
                    par['rew_cnt'] += 1
                    logIt(ID, "P", timeStart, timeEnd,push,"E") #log data for push reward
                else:
                    print("No more rewards for this side...")                            
                    logIt(ID, "X", timeStart, timeEnd,push,"R") #log data for failed push reward
            elif push == "T":
                print("Reset timeout reached during training, continue training...")
                logIt(ID, "T", timeStart, timeEnd,"N","E")
        else:
            logIt(ID, "D", timeStart, timeEnd,"N","E") #log data for entry reward        
    else:
        par['curr_test'] = 1


def endBlock():
    global slidingWindow
    print("Block ended")
    par['trial_cnt'] = 0
    par['curr_block'] += 1
    par['failed_trials'] = 0
    par['trial_suc_cnt'] = 0
    slidingWindow=[0]*par['trials_in_block']
    

def blockSuccess():
    print("Block was successfull")
    par['block_suc_cnt'] += 1           
    if par['block_suc_cnt'] >= par['blocks_to_pass']:
        par['curr_test'] += 1
        par['block_suc_cnt'] = 0
        if par['curr_test'] > len(tests) and par['loop_test'] > 0:
            par['curr_test'] = par['loop_test']


def blockFail():
    print("Block failed")
    par['failed_blocks']+=1
    if par['failed_blocks'] >= par['max_failed_blocks'] and par['max_failed_blocks'] > 0:
        leds.turnBothOff()
        timeout(int(par['failed_blocks_timout']*60))
        par['failed_blocks']=0
        playSound("beep_hi.wav")

        
def blockReset():
    # Reset the current block
    global slidingWindow
    global prevAnswer
    print("Block reset")
    par['trial_cnt'] = 0
    #par['curr_block'] += 1
    par['failed_trials'] = 0
    par['failed_current_trial'] = 0
    par['trial_suc_cnt'] = 0
    par['reset_blocks'] += 1
    slidingWindow=[0]*par['trials_in_block']
    prevAnswer='X'

    
def testReset():
    # Reset the current test
    print("Test reset")
    blockReset()
    par['block_suc_cnt'] = 0
    par['failed_blocks'] = 0

    
def experimentReset():
    # Reset the experiment back to the first test
    print("Experiment reset")
    testReset()
    par['curr_test'] = 1

    
def totalReset():
    # Reset the experiment back to training mode
    print("Experiment reset")
    testReset()
    par['curr_test'] = 0
        
        
def testing():
    global push
    global prevAnswer
    print("Testing mode...")
    test_index = par['curr_test']
    if test_index > len(tests) or test_index==0:
        return
    test = tests[test_index-1]    #subtract 1 because the count starts with zero
    if test.startswith("random"):
        #choose an image from the list at random
        answer = random.choice(testDict[test]) 
    elif test.startswith("shuffle"):
        print("Shuffled tests list:", par["previous_shuffle"])
        reshuffle=((par['trial_cnt'] % len(testDict[test]) == 0) and
                   (par['failed_current_trial'] == 0))
        if reshuffle or len(par["previous_shuffle"])==0:
            print("Shuffling tests")
            par["previous_shuffle"] = testDict[test]
            random.shuffle(par["previous_shuffle"])
            answer = par["previous_shuffle"][0]
        else:
            print("Selecting next image")
            answer = par["previous_shuffle"][par['trial_cnt'] % len(par["previous_shuffle"])]
    else:
        lisOfAnswers = testDict[test]
        answer = lisOfAnswers[par['trial_cnt'] % len(lisOfAnswers)] 
    answer, ledConfig = answer.split('-')
    print("Test:", test, " ", answer)
    if answer == "S":
        answer = prevAnswer
    elif answer == "O":
        answer = OPPOSITE_ANSWERS[prevAnswer]
    if answer not in LEGAL_ANSWERS:
        if answer == "X":
            #raise Exception("Answers based on previous input (S or O) cannot "
            #                "be used in the first trial.")
            answer="I"
        else:
            raise Exception("Answer " + str(answer) + " not a legal answer. "
                            "Ensure the answer is in: " + str(LEGAL_ANSWERS))
    #get the time of initial detection
    leds.setLEDs(ledConfig)
    timeStart = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S') 
    pushWait() #wait for button push or animal departure

    #get the time of initial detection    
    timeEnd = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if push == "T":
        # The timeout condition was reached
        print("Reset timeout reached during testing, resetting test...")
        blockReset()
        logIt(ID, "T", timeStart, timeEnd,"N","E")
    elif push != "D": #animal pushed a button    
        if push == answer or answer == "E" or answer == "I":
            #if the animal got it right..
            feedIt()
            print("test reward")
            par['trial_suc_cnt'] += 1  #advance count of successful trials 
            par['rew_cnt'] += 1   #advance total daily reward count
            par['failed_current_trial']=0
            slidingWindow[par['trial_cnt'] % par['trials_in_block']] = 1
            logIt(ID, "S", timeStart, timeEnd,push,answer)
            if answer == "I":
                prevAnswer=push
        elif push != answer:
            print("wrong. test failed", flush = True)
            playSound("beep_low.wav")                    
            par['failed_trials']+=1
            par['failed_current_trial']+=1
            slidingWindow[par['trial_cnt'] % par['trials_in_block']] = 0
            logIt(ID, "F", timeStart, timeEnd,push,answer)
            # Change to monitor departure.
            leds.turnBothOff()
            timeout(par['fail_delay'])
            if par['fail_trial_repeat'] >= par['failed_current_trial']:
                par['trial_cnt']-=1
            else:
                par['failed_current_trial']=0
            if par['failed_trials'] >= par['max_failed_trails'] and par['max_failed_trails'] > 0:
                timeout(par['failed_trails_timeout'])
                par['failed_trials']=0
                playSound("beep_hi.wav")
        # JH: Trial count should be updated after logging, so the
        # correct number is logged
        par['trial_cnt'] += 1
        if par["consecutive_block"]:
            if sum(slidingWindow) >= par['block_suc_thresh']:
                blockSuccess()
                endBlock()
        elif par['trial_cnt'] >= par['trials_in_block']:
            if par['trial_suc_cnt'] >= par['block_suc_thresh']:
                blockSuccess()
            else:
                blockFail()
            endBlock()              
    else: #animal departed
        logIt(ID, "D", timeStart, timeEnd,"N","E") #log data for entry reward


def startDay():
    timeNow = datetime.datetime.now() #.strftime('%Y-%m-%d %H:%M:%S') #get the time of initial detection
    dayNow = timeNow -  datetime.timedelta(hours=12) #subtract 12 hours when defining the day
    dayNow = dayNow.day
    timeStart = timeNow.strftime('%Y-%m-%d %H:%M:%S')
    print("Start time: " + timeStart)
    print("parameters read") 
    print(timeStart)
    if dayNow != par['rew_day']: #Check if we are starting a new day
        par['rew_day'] = dayNow #This line is necessary - updates day variable.  
        #Here's what gets reset on the next day.
        #Comment out what should not be reset.
        par['entry_cnt'] = 0
        par['push_cnt_e'] = 0
        par['push_cnt_r'] = 0
        par['push_cnt_l'] = 0
        par['trial_cnt'] = 0    
        par['trial_suc_cnt'] = 0
        par['curr_block'] = 0
        par['block_suc_cnt'] = 0    
        par['curr_test'] = 0
        par['rew_cnt'] = 0
        par['failed_trials'] = 0
        par['failed_blocks'] = 0
        par['failed_current_trial'] = 0
        
############### MAIN PROGRAM ##################################

def main():
    # Declare global variables
    global p
    global push
    global prev_push
    global timeStart
    global screen

    # Setup GPIO interface to feeder, IR, etc.
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(PIN_REMOTE_IN, GPIO.IN)  # This is the input pin from the remote control
    GPIO.setup(PIN_MOTOR_SNAP, GPIO.IN, pull_up_down = GPIO.PUD_UP)  #Input for motor snap switch. requires pull up enabled 
    GPIO.setup(PIN_MOTOR_RIGHT, GPIO.OUT) #Motor control - set high to turn motor right (facing spindle)
    GPIO.setup(PIN_MOTOR_LEFT, GPIO.OUT) #Motor control - set high to turn motor left (facing spindle)
    GPIO.setup(PIN_JOY_RIGHT, GPIO.IN, pull_up_down = GPIO.PUD_UP)  #Input for right screen button. requires pull up enabled 
    GPIO.setup(PIN_JOY_LEFT, GPIO.IN, pull_up_down = GPIO.PUD_UP)  #Input for left screen button. requires pull up enabled
    GPIO.setup(PIN_LED_RIGHT, GPIO.OUT) # Output for the right LED
    GPIO.setup(PIN_LED_LEFT, GPIO.OUT) # Output for the left LED
    
    GPIO.output(PIN_MOTOR_RIGHT, 0) #motor in standby
    GPIO.output(PIN_MOTOR_LEFT, 0) #motor in standby
    
    # Set up interrupts for when we are listening for button pushes on the monitor
    GPIO.add_event_detect(PIN_JOY_LEFT, GPIO.FALLING, callback=pushed, bouncetime=500)    
    GPIO.add_event_detect(PIN_JOY_RIGHT, GPIO.FALLING, callback=pushed, bouncetime=500)
    GPIO.add_event_detect(PIN_REMOTE_IN, GPIO.RISING, callback=remote, bouncetime=500)
    
    # Start pygame
    pygame.mixer.pre_init(22050, -16, 1, 1024) #Tradeoff between speed and fidelity here
    pygame.mixer.init()
    pygame.display.init()
    if MODE != "fullscreen":    
        screen = pygame.display.set_mode((1280,768))
    else:
        screen = pygame.display.set_mode((1280,768), pygame.FULLSCREEN)

    # JH: While the current code is designed for working with LEDs, rather than
    # a screen, we'll show an empty screen so we can interface with pygame.
    showImg("black.jpg")
    leds.turnBothOn()

    getParams() #initialize parameters, just to avoid 'par not defined' errors
    quitgame = 0    # Used as a flag to signal a keystroke--which stops the program
    push = "D"      # Indicates animal not present (D = departed)
    prev_push = "D" # Indicates there was no animal at the previous step either

    # JH: Added variables to keep track of information
    par['failed_trials'] = 0
    par['failed_blocks'] = 0
    par['failed_current_trial'] = 0

    startDay()

    while quitgame == 0:
        # If there is no animal, wait for an animal
        if par['rew_cnt'] < par['rew_max'] and par['curr_test'] <= len(tests):
            if par['curr_test'] == 0: #Training mode - not testing yet
                training()
            else:  #Testing mode
                testing()                
        else:  #do the following if the reward maximum has been reached
            leds.turnBothOff()
            while True:
                print("Out of reward, waiting for animal to leave...", flush=True)
                 #get the time of initial detection
                timeStart = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')    
                pushWait() #wait for button push or animal departure
                if push == "D":  
                    break      #break infinite loop if animal has left.                
                playSound("beep_low.wav")
                #get the time of initial detection
                timeEnd = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                #log data for entry reward
                logIt(ID, "M", timeStart, timeEnd,push,"N") 
            writeParam()   
    cleanup()


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
        if err.args[0]=="exit request":
            cleanup()
        else:
            logError()
            cleanup()
            raise
