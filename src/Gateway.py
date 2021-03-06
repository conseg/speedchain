import sys
import os
from os import listdir
from os.path import isfile, join
import time
import threading
import pickle
import socket
import traceback
import thread
import random
import json

from flask import Flask, request

import Pyro4
import merkle
from Crypto.PublicKey import RSA

# SpeedCHAIN modules
import Logger as Logger
import CryptoFunctions
import ChainFunctions
import PeerInfo
import DeviceInfo
import DeviceKeyMapping
import Transaction


def getMyIP():
    """ Return the IP from the gateway
    @return str
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    myIP = s.getsockname()[0]
    s.close()
    return myIP


def getTime():
    """ Return the current time
    @return str
    """
    return time.time()


lock = thread.allocate_lock()
consensusLock = thread.allocate_lock()
blockConsensusCandidateList = []
smartcontractLockList = []
blockContext = "0001"

# Enable/Disable the transaction validation when peer receives a transaction
validatorClient = True

myName = socket.gethostname()

app = Flask(__name__)
peers = []
genKeysPars = []
myURI = ""
gwPvt = ""
gwPub = ""
myOwnBlock = ""
orchestratorObject = ""
consensus = "None"  # it can be None, dBFT, PBFT, PoW, Witness3
# list of votes for new orchestrator votes are: voter gwPub, voted gwPub, signature
votesForNewOrchestrator = []
myVoteForNewOrchestrator = []  # my gwPub, voted gwPub, my signed vote


def bootstrapChain2():
    """ generate the RSA key pair for the gateway and create the chain"""
    global gwPub
    global gwPvt
    ChainFunctions.startBlockChain()
    gwPub, gwPvt = CryptoFunctions.generateRSAKeyPair()

#############################################################################
#############################################################################
#########################    PEER MANAGEMENT  ###############################
#############################################################################
#############################################################################


def findPeer(peerURI):
    """ Receive the peer URI generated automatically by pyro4 and verify if it on the network\n
        @param peerURI URI from the peer wanted\n
        @return True - peer found\n
        @return False - peer not found
    """
    global peers
    for p in peers:
        if p.peerURI == peerURI:
            return True
    return False


def getPeer(peerURI):
    """ Receive the peer URI generated automatically by pyro4 and return the peer object\n
        @param peerURI URI from the peer wanted\n
        @return p - peer object \n
        @return False - peer not found
    """
    global peers
    for p in peers:
        if p.peerURI == peerURI:
            return p
    return False


def addBack(peer, isFirst):
    """ Receive a peer object add it to a list of peers.\n
        the var isFirst is used to ensure that the peer will only be added once.\n
        @param peer - peer object\n
        @param isFirst - Boolean condition to add only one time a peer
    """
    global myURI
    if(isFirst):
        obj = peer.object
        obj.addPeer(myURI, isFirst)
        # pickedUri = pickle.dumps(myURI)
        # print("Before gettin last chain blocks")
        # print("Picked URI in addback: " + str(pickedUri))
        # obj.getLastChainBlocks(pickedUri, 0)
    # else:
    #    print ("done adding....")


def sendTransactionToPeers(devPublicKey, transaction):
    """ Send a transaction received to all peers connected.\n
        @param devPublickey - public key from the sending device\n
        @param transaction - info to be add to a block
    """
    global peers
    for peer in peers:
        obj = peer.object
        # logger.debug("Sending transaction to peer " + peer.peerURI)
        trans = pickle.dumps(transaction)
        obj.updateBlockLedger(devPublicKey, trans)

# class sendBlks(threading.Thread):
#     def __init__(self, threadID, iotBlock):
#         threading.Thread.__init__(self)
#         self.threadID = threadID
#         self.iotBlock = iotBlock
#
#     def run(self):
#         print "Starting "
#         # Get lock to synchronize threads
#         global peers
#         for peer in peers:
#             print ("runnin in a thread: ")
#             obj = peer.object
#             # logger.debug("sending IoT Block to: " + peer.peerURI)
#             dat = pickle.dumps(self.iotBlock)
#             obj.updateIOTBlockLedger(dat)


def sendBlockToPeers(IoTBlock):
    """
    Receive a block and send it to all peers connected.\n
    @param IoTBlock - BlockHeader object
    """
    global peers
    # print("sending block to peers")
    # logger.debug("Running through peers")
    for peer in peers:
        # print ("Inside for in peers")
        obj = peer.object
        # print("sending IoT Block to: " + str(peer.peerURI))
        # logger.debug("Sending block to peer " + str(peer.peerURI))
        dat = pickle.dumps(IoTBlock)
        obj.updateIOTBlockLedger(dat, myName)
    # print("block sent to all peers")


def syncChain(newPeer):
    """
    Send the actual chain to a new peer\n
    @param newPeer - peer object

    TODO update this pydoc after write this method code
    """
    # write the code to identify only a change in the iot block and insert.
    return True


def connectToPeers(nameServer):
    """this method recieves a nameServer parameter, list all remote objects connected to it, and
    add these remote objetcts as peers to the current node \n
    @param nameServer - list all remote objects connected to it
    """
    # print ("found # results:"+str(len(nameServer.list())))
    for peerName in nameServer.list():
        if(peerName != gatewayName and peerName != "Pyro.NameServer"):
            # print ("adding new peer:"+peerURI)
            peerURI = nameServer.lookup(peerName)
            addPeer2(peerURI)
            # orchestratorObject
        # else:
            # print ("nothing to do")
            # print (peerURI )
    # print ("finished connecting to all peers")


def addPeer2(peerURI):
    """ Receive a peerURI and add the peer to the network if it is not already in\n
        @param peerURI - peer id on the network\n
        @return True - peer added to the network\n
        @return False - peer already in the network
    """
    global peers
    if not (findPeer(peerURI)):
        # print ("peer not found. Create new node and add to list")
        # print ("[addPeer2]adding new peer:" + peerURI)
        newPeer = PeerInfo.PeerInfo(peerURI, Pyro4.Proxy(peerURI))
        peers.append(newPeer)
        # print("Runnin addback...")
        addBack(newPeer, True)
        # syncChain(newPeer)
        # print ("finished addback...")
        return True
    return False

#############################################################################
#############################################################################
#########################    CRIPTOGRAPHY    ################################
#############################################################################
#############################################################################


def generateAESKey(devPubKey):
    """ Receive a public key and generate a private key to it with AES 256\n
        @param devPubKey - device public key\n
        @return randomAESKey - private key linked to the device public key
    """
    global genKeysPars
    randomAESKey = os.urandom(32)  # AES key: 256 bits
    obj = DeviceKeyMapping.DeviceKeyMapping(devPubKey, randomAESKey)
    genKeysPars.append(obj)
    return randomAESKey


def findAESKey(devPubKey):
    """ Receive the public key from a device and found the private key linked to it\n
        @param devPubKey - device public key\n
        @return AESkey - found the key\n
        @return False - public key not found
    """
    global genKeysPars
    for b in genKeysPars:
        if (b.publicKey == devPubKey):
            return b.AESKey
    return False

#############################################################################
#############################################################################
#################    Consensus Algorithm Methods    #########################
#############################################################################
#############################################################################


answers = {}
trustedPeers = []


def addTrustedPeers():
    """ Run on the peers list and add all to a list called trustedPeers """
    global peers
    for p in peers:
        trustedPeers.append(p.peerURI)

# Consensus PoW
# TODO -> should create a nonce in the block and in the transaction in order to generate it
# we could add also a signature set (at least 5 as ethereum or 8 as bitcoin?) to do before send the block for update
# peers should verify both block data, hash, timestamp, etc and the signatures, very similar to what is done by verifyBlockCandidate
# maybe this verifications could be put in a another method... maybe something called " verifyBlockData "
# END NEW CONSENSUS @Roben
##########################


def peerIsTrusted(i):
    global trustedPeers
    for p in trustedPeers:
        if p == i:
            return True
    return False


def peerIsActive(i):
    return True  # TO DO


def sendBlockToConsensus(newBlock, gatewayPublicKey, devicePublicKey):
    obj = peer.object
    data = pickle.dumps(newBlock)
    obj.isValidBlock(data, gatewayPublicKey, devicePublicKey)


def receiveBlockConsensus(self, data, gatewayPublicKey, devicePublicKey, consensus):
    newBlock = pickle.loads(data)
    answer[newBlock].append(consensus)


def isValidBlock(self, data, gatewayPublicKey, devicePublicKey, peer):
    newBlock = pickle.loads(data)
    blockIoT = ChainFunctions.findBlock(devicePublicKey)
    consensus = True
    if blockIoT == False:
        # print("Block not found in IoT ledger")
        consensus = False

    lastBlock = blockIoT.blockLedger[len(blockIoT.blockLedger) - 1]
    if newBlock.index != lastBlock.index + 1:
        # print("New blovk Index not valid")
        consensus = False

    if lastBlock.calculateHashForBlockLedger(lastBlock) != newBlock.previousHash:
        # print("New block previous hash not valid")
        consensus = False

    now = "{:.0f}".format(((time.time() * 1000) * 1000))

    # check time
    if not (newBlock.timestamp > newBlock.signature.timestamp and newBlock.timestamp < now):
        # print("New block time not valid")
        consensus = False

    # check device time
    if not (newBlock.signature.timestamp > lastBlock.signature.timestamp and newBlock.signature.timestamp < now):
        # print("New block device time not valid")
        consensus = False

    # check device signature with device public key
    if not (CryptoFunctions.signVerify(newBlock.signature.data, newBlock.signature.deviceSignature, gatewayPublicKey)):
        # print("New block device signature not valid")
        consensus = False
    peer = getPeer(peer)
    obj = peer.object
    obj.receiveBlockConsensus(data, gatewayPublicKey,
                              devicePublicKey, consensus)


def isTransactionValid(transaction, pubKey):
    data = str(transaction.data)[-22:-2]
    signature = str(transaction.data)[:-22]
    res = CryptoFunctions.signVerify(data, signature, pubKey)
    return res


def isBlockValid(block):
    # Todo Fix the comparison between the hashes... for now is just a mater to simulate the time spend calculating the hashes...
    # global BlockHeaderChain
    # print(str(len(BlockHeaderChain)))
    lastBlk = ChainFunctions.getLatestBlock()
    # print("Index:"+str(lastBlk.index)+" prevHash:"+str(lastBlk.previousHash)+ " time:"+str(lastBlk.timestamp)+ " pubKey:")
    # lastBlkHash = CryptoFunctions.calculateHash(lastBlk)

    lastBlkHash = CryptoFunctions.calculateHash(
        lastBlk.index, lastBlk.previousHash, lastBlk.timestamp, lastBlk.nonce, lastBlk.publicKey, lastBlk.blockContext)

    # print ("This Hash:"+str(lastBlkHash))
    # print ("Last Hash:"+str(block.previousHash))
    if(lastBlkHash == block.previousHash):
        # logger.info("isBlockValid == true")
        return True
    else:
        logger.error("isBlockValid == false")
        logger.error("lastBlkHash = " + str(lastBlkHash))
        logger.error("block.previous = " + str(block.previousHash))
        logger.error("lastBlk Index = " + str(lastBlk.index))
        logger.error("block.index = " + str(block.index))
        # return False
        return True

#############################################################################
#############################################################################
######################      R2AC Class    ###################################
#############################################################################
#############################################################################


@Pyro4.expose
@Pyro4.behavior(instance_mode="single")
class R2ac(object):
    def __init__(self):
        """ Init the R2AC chain on the peer"""
        logger.info("SpeedyCHAIN Gateway initialized")

    def addTransaction(self, devPublicKey, encryptedObj):
        """ Receive a new transaction to be add to the chain, add the transaction
            to a block and send it to all peers\n
            @param devPublicKey - Public key from the sender device\n
            @param encryptedObj - Info of the transaction encrypted with AES 256\n
            @return "ok!" - all done\n
            @return "Invalid Signature" - an invalid key are found\n
            @return "Key not found" - the device's key are not found
        """
        # logger.debug("Transaction received")
        global gwPvt
        global gwPub
        t1 = time.time()
        blk = ChainFunctions.findBlock(devPublicKey)
        if (blk != False and blk.index > 0):
            devAESKey = findAESKey(devPublicKey)
            if (devAESKey != False):
                # logger.info("Appending transaction to block #" +
                #             str(blk.index) + "...")
                # plainObject contains [Signature + Time + Data]

                plainObject = CryptoFunctions.decryptAES(
                    encryptedObj, devAESKey)
                signature = plainObject[:-20]  # remove the last 20 chars
                # remove the 16 char of timestamp
                devTime = plainObject[-20:-4]
                # retrieve the las 4 chars which are the data
                deviceData = plainObject[-4:]

                d = devTime+deviceData
                isSigned = CryptoFunctions.signVerify(
                    d, signature, devPublicKey)

                if isSigned:
                    deviceInfo = DeviceInfo.DeviceInfo(
                        signature, devTime, deviceData)
                    nextInt = blk.transactions[len(
                        blk.transactions) - 1].index + 1
                    signData = CryptoFunctions.signInfo(gwPvt, str(deviceInfo))
                    gwTime = "{:.0f}".format(((time.time() * 1000) * 1000))
                    # code responsible to create the hash between Info nodes.
                    prevInfoHash = CryptoFunctions.calculateTransactionHash(
                        ChainFunctions.getLatestBlockTransaction(blk))

                    transaction = Transaction.Transaction(
                        nextInt, prevInfoHash, gwTime, deviceInfo, signData,0)

                    # send to consensus
                    # if not consensus(newBlockLedger, gwPub, devPublicKey):
                    #    return "Not Approved"
                    # if not PBFTConsensus(blk, gwPub, devPublicKey):
                    #     return "Consensus Not Reached"

                    ChainFunctions.addBlockTransaction(blk, transaction)
                    # logger.debug("Block #" + str(blk.index) + " added locally")
                    # logger.debug("Sending block #" +
                    #             str(blk.index) + " to peers...")
                    t2 = time.time()
                    logger.info("gateway;" + gatewayName + ";" + consensus + ";T1;Time to add a new transaction in a block;" + '{0:.12f}'.format((t2 - t1) * 1000))
                    # --->> this function should be run in a different thread.
                    sendTransactionToPeers(devPublicKey, transaction)
                    # print("all done")
                    return "ok!"
                else:
                    # logger.debug("--Transaction not appended--Transaction Invalid Signature")
                    return "Invalid Signature"
            # logger.debug("--Transaction not appended--Key not found")
            return "key not found"

##############################
################ To add an Smart Contract transaction can be done in 2 ways
#################### method was overloaded
#######################################################
    def addSCinLockList(self,devPublicKey):
        while(devPublicKey in smartcontractLockList):
            time.sleep(0.01)
        smartcontractLockList.append(devPublicKey)
        return True

    def addTransactionSC2(self, transactionData,signedDatabyDevice,devPublicKey,devTime):
        """ Receive a new transaction to be add to the chain, add the transaction
            to a block and send it to all peers\n
            @param devPublicKey - Public key from the sender device\n
            @param encryptedObj - Info of the transaction encrypted with AES 256\n
            @return "ok!" - all done\n
            @return "Invalid Signature" - an invalid key are found\n
            @return "Key not found" - the device's key are not found
        """
        # logger.debug("Transaction received")

        global smartcontractLockList
        global gwPvt
        global gwPub
        t1 = time.time()
        blk = ChainFunctions.findBlock(devPublicKey)

        self.addSCinLockList(devPublicKey)
            #wait

        # if (consensus == "dBFT" or consensus == "Witness3"):
        #     # consensusLock.acquire(1) # only 1 consensus can be running at same time
        #     # for p in peers:
        #     #     obj=p.object
        #     #     obj.acquireLockRemote()
        #     self.lockForConsensus()
        #     # print("ConsensusLocks acquired!")
        #     orchestratorObject.addBlockConsensusCandidate(pickedKey)
        #     orchestratorObject.rundBFT()
        #
        #processing....
        #
        #
        #at end...


        if (blk != False and blk.index > 0):

                isSigned = True #ToDo verify device signature

                if isSigned:
                    # print("it is signed!!!")
                    deviceInfo = DeviceInfo.DeviceInfo(signedDatabyDevice, devTime, transactionData)
                    nextInt = blk.transactions[len(
                        blk.transactions) - 1].index + 1
                    signData = CryptoFunctions.signInfo(gwPvt, str(deviceInfo))
                    gwTime = "{:.0f}".format(((time.time() * 1000) * 1000))
                    # code responsible to create the hash between Info nodes.
                    prevInfoHash = CryptoFunctions.calculateTransactionHash(
                        ChainFunctions.getLatestBlockTransaction(blk))

                    transaction = Transaction.Transaction(
                        nextInt, prevInfoHash, gwTime, deviceInfo, signData, 0) #nonce = 0
                    #
                    #Set a lock for each device/sc pubkey
                    #verify lock
                    #perform consensus if it is not locked
                    # send to consensus
                    # if not consensus(newBlockLedger, gwPub, devPublicKey):
                    #    return "Not Approved"
                    # if not PBFTConsensus(blk, gwPub, devPublicKey):
                    #     return "Consensus Not Reached"

                    ChainFunctions.addBlockTransaction(blk, transaction)
                    # logger.debug("Block #" + str(blk.index) + " added locally")
                    # logger.debug("Sending block #" +
                    #              str(blk.index) + " to peers...")
                    t2 = time.time()
                    logger.info("gateway;" + gatewayName + ";" + consensus + ";T1;Time to add a new transaction in a block;" + '{0:.12f}'.format((t2 - t1) * 1000))
                    # --->> this function should be run in a different thread.
                    sendTransactionToPeers(devPublicKey, transaction)
                    # print("all done in transations")
                    smartcontractLockList.remove(devPublicKey)
                    return "ok!"
                else:
                    # print("Signature is not ok")
                    # logger.debug("--Transaction not appended--Transaction Invalid Signature")
                    smartcontractLockList.remove(devPublicKey)
                    return "Invalid Signature"
            # logger.debug("--Transaction not appended--Key not found")
        smartcontractLockList.remove(devPublicKey)
        return "key not found"

    def addTransactionSC(self, devPublicKey, encryptedObj):
        """ Receive a new transaction to be add to the chain, add the transaction
            to a block and send it to all peers\n
            @param devPublicKey - Public key from the sender device\n
            @param encryptedObj - Info of the transaction encrypted with AES 256\n
            @return "ok!" - all done\n
            @return "Invalid Signature" - an invalid key are found\n
            @return "Key not found" - the device's key are not found
        """
        # logger.debug("Transaction received")
        global gwPvt
        global gwPub
        t1 = time.time()
        blk = ChainFunctions.findBlock(devPublicKey)
        if (blk != False and blk.index > 0):
            devAESKey = findAESKey(devPublicKey)
            if (devAESKey != False):
                # logger.info("Appending transaction to block #" +
                #             str(blk.index) + "...")
                # plainObject contains [Signature + Time + Data]

                plainObject = CryptoFunctions.decryptAES(
                    encryptedObj, devAESKey)
                # retrieve the last chars, excluding timestamp and signature
                deviceData = plainObject[(172+16):]
                # remove the last 20 chars
                signature = plainObject[:-(16+len(deviceData))]
                # print("###Signature after receiving: "+signature)
                # print("###Device Data: "+deviceData)
                # remove the 16 char of timestamp
                devTime = plainObject[-(16+len(deviceData)):-len(deviceData)]
                # print("###devTime: "+devTime)

                d = devTime+deviceData
                isSigned = CryptoFunctions.signVerify(
                    d, signature, devPublicKey)

                if isSigned:
                    # print("it is signed!!!")
                    deviceInfo = DeviceInfo.DeviceInfo(
                        signature, devTime, deviceData)
                    nextInt = blk.transactions[len(
                        blk.transactions) - 1].index + 1
                    signData = CryptoFunctions.signInfo(gwPvt, str(deviceInfo))
                    gwTime = "{:.0f}".format(((time.time() * 1000) * 1000))
                    # code responsible to create the hash between Info nodes.
                    prevInfoHash = CryptoFunctions.calculateTransactionHash(
                        ChainFunctions.getLatestBlockTransaction(blk))

                    transaction = Transaction.Transaction(
                        nextInt, prevInfoHash, gwTime, deviceInfo, signData,0)#nonce=0

                    # send to consensus
                    # if not consensus(newBlockLedger, gwPub, devPublicKey):
                    #    return "Not Approved"
                    # if not PBFTConsensus(blk, gwPub, devPublicKey):
                    #     return "Consensus Not Reached"

                    ChainFunctions.addBlockTransaction(blk, transaction)
                    # logger.debug("Block #" + str(blk.index) + " added locally")
                    # logger.debug("Sending block #" +
                    #              str(blk.index) + " to peers...")
                    t2 = time.time()
                    logger.info("gateway;" + gatewayName + ";" + consensus + ";T1;Time to add a new transaction in a block;" + '{0:.12f}'.format((t2 - t1) * 1000))
                    # --->> this function should be run in a different thread.
                    sendTransactionToPeers(devPublicKey, transaction)
                    # print("all done in transations")
                    return "ok!"
                else:
                    # print("Signature is not ok")
                    # logger.debug("--Transaction not appended--Transaction Invalid Signature")
                    return "Invalid Signature"
            # logger.debug("--Transaction not appended--Key not found")
            return "key not found"

    def updateBlockLedger(self, pubKey, transaction):
        # update local bockchain adding a new transaction
        """ Receive a new transaction and add it to the chain\n
            @param pubKey - Block public key\n
            @param transaction - Data to be insert on the block\n
            @return "done" - method done (the block are not necessarily inserted)
        """
        trans = pickle.loads(transaction)
        t1 = time.time()
        # logger.info("Received transaction #" + (str(trans.index)))
        blk = ChainFunctions.findBlock(pubKey)
        if blk != False:
            # logger.debug("Transaction size in the block = " +
            #              str(len(blk.transactions)))
            if not (ChainFunctions.blockContainsTransaction(blk, trans)):
                if validatorClient:
                    isTransactionValid(trans, pubKey)
                ChainFunctions.addBlockTransaction(blk, trans)
        t2 = time.time()
        logger.info("gateway;" + gatewayName + ";" + consensus + ";T2;Time to add a transaction in block ledger;" + '{0:.12f}'.format((t2 - t1) * 1000))
        return "done"

    def updateIOTBlockLedger(self, iotBlock, gwName):
        # update local bockchain adding a new block
        """ Receive a block and add it to the chain\n
            @param iotBlock - Block to be add\n
            @param gwName - sender peer's name
        """
        # print("Updating IoT Block Ledger, in Gw: "+str(gwName))
        # logger.debug("updateIoTBlockLedger Function")
        b = pickle.loads(iotBlock)
        # print("picked....")
        t1 = time.time()
        # logger.debug("Received block #" + (str(b.index)))
        # logger.info("Received block #" + str(b.index) +
        #             " from gateway " + str(gwName))
        if isBlockValid(b):
            # print("updating is valid...")
            ChainFunctions.addBlockHeader(b)
        t2 = time.time()
        # print("updating was done")
        logger.info("gateway;" + gatewayName + ";" + consensus + ";T3;Time to add a new block in block ledger;" + '{0:.12f}'.format((t2 - t1) * 1000))

    def addBlockConsensusCandidate(self, devPubKey):
        # TODO
        global blockConsensusCandidateList
        # logger.debug("================================================")
        # print("Inside addBlockConsensusCandidate, devPubKey: ")
        # print(devPubKey)
        devKey = pickle.loads(devPubKey)
        # print("Inside addBlockConsensusCandidate, devKey: ")
        # print(devPubKey)
        # logger.debug("This method is executed by orchestrator."+str(devKey))
        # logger.debug("received new block consensus candidate. Queue Size:"+srt(len(blockConsensusCandidateList)))
        addNewBlockToSyncList(devKey)
        # logger.debug("added to the sync list")
        # logger.debug("================================================")

    def acquireLockRemote(self):
        global consensusLock
        # with False argument, it will return true if it was locked or false if it could not be locked
        return consensusLock.acquire(False)
        # consensusLock.acquire(1)
        # return True

    def releaseLockRemote(self):
        global consensusLock
        consensusLock.release()

    def addBlock(self, devPubKey):
        """ Receive a device public key from a device and link it to a block on the chain\n
            @param devPubKey - request's device public key\n
            @return encKey - RSA encrypted key for the device be able to communicate with the peers
        """
        global gwPub
        global consensusLock
        # print("addingblock... DevPubKey:" + devPubKey)
        # logger.debug("|---------------------------------------------------------------------|")
        # logger.info("Block received from device")
        aesKey = ''
        t1 = time.time()
        blk = ChainFunctions.findBlock(devPubKey)
        if (blk != False and blk.index > 0):
            # print("inside first if")
            aesKey = findAESKey(devPubKey)

            if aesKey == False:
                # print("inside second if")
                # logger.info("Using existent block data")
                aesKey = generateAESKey(blk.publicKey)
                encKey = CryptoFunctions.encryptRSA2(devPubKey, aesKey)
                t2 = time.time()
        else:
            # print("inside else")
            # logger.debug("***** New Block: Chain size:" +
            #              str(ChainFunctions.getBlockchainSize()))
            pickedKey = pickle.dumps(devPubKey)
            aesKey = generateAESKey(devPubKey)
            # print("pickedKey: ")
            # print(pickedKey)

            encKey = CryptoFunctions.encryptRSA2(devPubKey, aesKey)
            t2 = time.time()
            # Old No Consensus
            # bl = ChainFunctions.createNewBlock(devPubKey, gwPvt)
            # sendBlockToPeers(bl)
            # logger.debug("starting block consensus")
            #############LockCONSENSUS STARTS HERE###############
            if(consensus == "PBFT"):
                # PBFT elect new orchestator every time that a new block should be inserted
                # allPeersAreLocked = False
                self.lockForConsensus()
                # print("ConsensusLocks acquired!")
                self.electNewOrchestrator()
                orchestratorObject.addBlockConsensusCandidate(pickedKey)
                orchestratorObject.runPBFT()
            if(consensus == "dBFT" or consensus == "Witness3"):
                print("indo pro dbft")
                # consensusLock.acquire(1) # only 1 consensus can be running at same time
                # for p in peers:
                #     obj=p.object
                #     obj.acquireLockRemote()
                self.lockForConsensus()

                orchestratorObject.addBlockConsensusCandidate(pickedKey)
                print("blockadded!")
                orchestratorObject.rundBFT()
                print("after rundbft")
            if(consensus == "PoW"):
                # consensusLock.acquire(1) # only 1 consensus can be running at same time
                # for p in peers:
                #     obj=p.object
                #     obj.acquireLockRemote()
                self.lockForConsensus()
                # print("ConsensusLocks acquired!")
                self.addBlockConsensusCandidate(pickedKey)
                self.runPoW()
            if(consensus == "None"):
                self.addBlockConsensusCandidate(pickedKey)
                self.runNoConsesus()

            # print("after orchestratorObject.addBlockConsensusCandidate")
            # try:
            # PBFTConsensus(bl, gwPub, devPubKey)
            # except KeyboardInterrupt:
            #     sys.exit()
            # except:
            #     print("failed to execute:")
            #     logger.error("failed to execute:")
            #     exc_type, exc_value, exc_traceback = sys.exc_info()
            #     print "*** print_exception:"    l
            #     traceback.print_exception(exc_type, exc_value, exc_traceback,
            #                           limit=6, file=sys.stdout)
            #
            # logger.debug("end block consensus")
            # try:
            #     #thread.start_new_thread(sendBlockToPeers,(bl))
            #     t1 = sendBlks(1, bl)
            #     t1.start()
            # except:
            #     print "thread not working..."

            if(consensus == "PBFT" or consensus == "dBFT" or consensus == "Witness3" or consensus == "PoW"):
                self.releaseLockForConsensus()
                for p in peers:
                    obj = p.object
                    obj.releaseLockRemote()
                # print("ConsensusLocks released!")
            ######end of lock consensus################

        # print("Before encription of rsa2")

        t3 = time.time()
        # logger.info("gateway;" + gatewayName + ";" + consensus + ";T1;Time to generate key;" + '{0:.12f}'.format((t2 - t1) * 1000))
        logger.info("gateway;" + gatewayName + ";" + consensus + ";T6;Time to add and replicate a new block in blockchain;" + '{0:.12f}'.format((t3 - t1) * 1000))
        # logger.debug("|---------------------------------------------------------------------|")
        # print("block added")
        return encKey

    def addPeer(self, peerURI, isFirst):
        """ Receive a peer URI add it to a list of peers.\n
            the var isFirst is used to ensure that the peer will only be added once.\n
            @param peerURI - peer URI\n
            @param isFirst - Boolean condition to add only one time a peer\n
            @return True - peer successfully added\n
            @return False - peer is already on the list
        """
        global peers
        if not (findPeer(peerURI)):
            newPeer = PeerInfo.PeerInfo(peerURI, Pyro4.Proxy(peerURI))
            peers.append(newPeer)
            if isFirst:
                # after adding the original peer, send false to avoid loop
                addBack(newPeer, False)
            syncChain(newPeer)
            return True
        else:
            # print("peer is already on the list")
            return False

    def showIoTLedger(self):
        """ Log all chain \n
            @return "ok" - done
        """
        # logger.info("Showing Block Header data for peer: " + myURI)
        print("Showing Block Header data for peer: " + myURI)
        size = ChainFunctions.getBlockchainSize()
        # logger.info("IoT Ledger size: " + str(size))
        # logger.info("|-----------------------------------------|")
        print("IoT Ledger size: " + str(size))
        print("|-----------------------------------------|")
        theChain = ChainFunctions.getFullChain()
        for b in theChain:
        # logger.info(b.strBlock())
        # logger.info("|-----------------------------------------|")
            print(b.strBlock())
            print("|-----------------------------------------|")
        return "ok"

    def showLastTransactionData(self, blockIndex):
        #print("Showing Data from Last Transaction from block #: " + str(blockIndex))
        blk = ChainFunctions.getBlockByIndex(blockIndex)
        lastTransactionInfo = ChainFunctions.getLatestBlockTransaction(blk).data
        transactionData = lastTransactionInfo.strInfoData()

        # print("My data is: "+str(transactionData))

        return transactionData

    def showBlockLedger(self, index):
        """ Log all transactions of a block\n
            @param index - index of the block\n
            @return "ok" - done
        """
        print("Showing Transactions data for peer: " + myURI)
        # logger.info("Showing Trasactions data for peer: " + myURI)
        blk = ChainFunctions.getBlockByIndex(index)
        print("Block for index"+str(index))
        size = len(blk.transactions)
        # logger.info("Block Ledger size: " + str(size))
        # logger.info("-------")
        print("Block Ledger size: " + str(size))
        print("-------")
        for b in blk.transactions:
            # logger.info(b.strBlock())
            # logger.info("-------")
            print(b.strBlock())
            print("-------")
        return "ok"

    def listPeer(self):
        """ Log all peers in the network\n
            @return "ok" - done
        """
        global peers
        # logger.info("|--------------------------------------|")
        # for p in peers:
        # logger.info("PEER URI: "+p.peerURI)
        # logger.info("|--------------------------------------|")
        return "ok"

    def calcMerkleTree(self, blockToCalculate):
        # print ("received: "+str(blockToCalculate))
        t1 = time.time()
        blk = ChainFunctions.getBlockByIndex(blockToCalculate)
        trans = blk.transactions
        size = len(blk.transactions)
        mt = merkle.MerkleTools()
        mt.add_leaf(trans, True)
        mt.make_tree()
        t2 = time.time()
        logger.info("gateway;" + gatewayName + ";" + consensus + ";T4;Time to compute merkle tree root (size = " + str(size) + ");" + '{0:.12f}'.format((t2 - t1) * 1000))
        return "ok"

    def getRemotePeerBlockChain(self):
        pickledChain = pickle.dumps(ChainFunctions.getFullChain())
        return pickledChain

    def getLastChainBlocks(self, peerURI, lastBlockIndex):
        # Get the missing blocks from orchestrator
        # print("Inside get last chain block...")
        chainSize = ChainFunctions.getBlockchainSize()
        # print("Chainsized: " + str(chainSize))
        if(chainSize > 1):
            newBlock = ChainFunctions.getBlockByIndex(1)
            # print("My Key is: "+ str(newBlock.publicKey) + "My index is" + str(newBlock.index))
        # destinationURI = pickle.loads(peerURI)
        # peerUri= getPeerbyPK(destinationPK)
            sendBlockToPeers(newBlock)
        # print("Inside get last chain block... requested by URI: "+destinationURI)
        # #peer=Pyro4.Proxy(destinationURI)
        # peer = PeerInfo.PeerInfo(destinationURI, Pyro4.Proxy(destinationURI))
        # obj = peer.object
        # print("After creating obj in getlastchain")
        # for index in range(lastBlockIndex+1, chainSize-1):
        #     # logger.debug("sending IoT Block to: " + str(peer.peerURI))
        #     print("Sending to peer"+ str(destinationURI) + "Block Index: "+ str(index) + "chainsize: "+ str(chainSize))
        #     newBlock=ChainFunctions.getBlockByIndex(index)
        #     #dat = pickle.dumps(ChainFunctions.getBlockByIndex(index))
        #     #obj.updateIOTBlockLedger(dat, myName)
        #     obj.ChainFunctions.addBlockHeader(newBlock)

        # print("For finished")

    def getMyOrchestrator(self):
        dat = pickle.dumps(orchestratorObject)
        return dat

    def addVoteOrchestrator(self, sentVote):
        global votesForNewOrchestrator
        dat = pickle.loads(sentVote)
        # print("adding vote in remote peer"+str(dat))
        votesForNewOrchestrator.append(dat)
        # print("finished adding vote for orchetrator")
        return True

    def peerVoteNewOrchestrator(self):
        global myVoteForNewOrchestrator
        global votesForNewOrchestrator
        randomGw = random.randint(0, len(peers) - 1)
        # randomGw=1
        votedURI = peers[randomGw].peerURI
        # print("VotedURI: " + str(votedURI))
        # myVoteForNewOrchestrator = [gwPub, votedURI, CryptoFunctions.signInfo(gwPvt, votedURI)]  # not safe sign, just for test
        myVoteForNewOrchestrator = votedURI
        votesForNewOrchestrator.append(myVoteForNewOrchestrator)
        pickedVote = pickle.dumps(myVoteForNewOrchestrator)
        return pickedVote

    def electNewOrchestrator(self):
        global votesForNewOrchestrator
        global orchestratorObject
        t1 = time.time()
        for peer in peers:
            obj = peer.object
            # print("objeto criado")
            receivedVote = obj.peerVoteNewOrchestrator()
            votesForNewOrchestrator.append(pickle.loads(receivedVote))
        voteNewOrchestrator()
        # newOrchestratorURI = mode(votesForNewOrchestrator)
        newOrchestratorURI = max(
            set(votesForNewOrchestrator), key=votesForNewOrchestrator.count)
        # print("Elected node was" + newOrchestratorURI)
        orchestratorObject = Pyro4.Proxy(newOrchestratorURI)
        for peer in peers:
            obj = peer.object
            dat = pickle.dumps(orchestratorObject)
            obj.loadElectedOrchestrator(dat)
        t2 = time.time()
        # logger.info("gateway;" + gatewayName + ";" + consensus + ";T7;Time to execute new election block consensus;" + '{0:.12f}'.format((t2 - t1) * 1000))
        # logger.info("New Orchestator loaded is: " + str(newOrchestratorURI))
        # orchestratorObject

    def loadElectedOrchestrator(self, data):
        global orchestratorObject
        newOrchestrator = pickle.loads(data)
        orchestratorObject = newOrchestrator
        # logger.info("New Orchestator loaded is: " + str(orchestratorObject.exposedURI()))
        # print("new loaded orchestrator: " + str(orchestratorObject.exposedURI()))
        return True

    def exposedURI(self):
        return myURI

    def setConsensus(self, receivedConsensus):
        global consensus
        if (receivedConsensus != consensus):
            consensus = receivedConsensus
            # print("######")
            # print("Changed my consensus to " + consensus)
            for p in peers:
                obj = p.object
                obj.setConsensus(receivedConsensus)
        return True

    def runPBFT(self):
        """ Run the PBFT consensus to add a new block on the chain """
        # print("I am in runPBFT")
        t1 = time.time()
        global gwPvt
        global blockContext
        devPubKey = getBlockFromSyncList()
        #verififyKeyContext()
        blockContext = "0001"
        #@TODO define somehow a device is in a context
        blk = ChainFunctions.createNewBlock(devPubKey, gwPvt, blockContext, consensus)
        # logger.debug("Running PBFT function to block(" + str(blk.index) + ")")

        PBFTConsensus(blk, gwPub, devPubKey)
        t2 = time.time()
        logger.info("gateway;" + gatewayName + ";" + consensus + ";T5;Time to add a new block with pBFT consensus algorithm;" + '{0:.12f}'.format((t2 - t1) * 1000))
        # print("Finish PBFT consensus in: "+ '{0:.12f}'.format((t2 - t1) * 1000))

    def rundBFT(self):
        """ Run the dBFT consensus to add a new block on the chain """
        # print("I am in rundBFT")
        t1 = time.time()
        global gwPvt
        global blockContext
        devPubKey = getBlockFromSyncList()
        #verififyKeyContext()
        blockContext = "0001"
        #@TODO define somehow a device is in a context
        blk = ChainFunctions.createNewBlock(devPubKey, gwPvt, blockContext, consensus)
        print("after blk, before consensus")
        # logger.debug("Running dBFT function to block(" + str(blk.index) + ")")
        PBFTConsensus(blk, gwPub, devPubKey)
        print("Consensus finished")
        t2 = time.time()
        logger.info("gateway;" + gatewayName + ";" + consensus + ";T5;Time to add a new block with dBFT consensus algorithm;" + '{0:.12f}'.format((t2 - t1) * 1000))
        # print("Finish dBFT consensus in: "+ '{0:.12f}'.format((t2 - t1) * 1000))

    def runPoW(self):
        # Consensus PoW
        """ Run the PoW consensus to add a new block on the chain """
        # print("I am in runPoW")
        t1 = time.time()
        global gwPvt
        global blockContext
        devPubKey = getBlockFromSyncList()
        #verififyKeyContext()
        blockContext = "0001"
        #@TODO define somehow a device is in a context
        blk = ChainFunctions.createNewBlock(devPubKey, gwPvt, blockContext, consensus)
        # print("Device PubKey (insire runPoW): " + str(devPubKey))

        if (PoWConsensus(blk, gwPub, devPubKey)):
            t2 = time.time()
            logger.info("gateway;" + gatewayName + ";" + consensus + ";T5;Time to add a new block with PoW consensus algorithm;" + '{0:.12f}'.format((t2 - t1) * 1000))
            # # print("Finish PoW consensus in: "+ '{0:.12f}'.format((t2 - t1) * 1000))
        else:
            t2 = time.time()
            logger.error("(Something went wrong) time to execute PoW Block Consensus = " +
                         '{0:.12f}'.format((t2 - t1) * 1000))
            # print("I finished runPoW - Wrong")

    def runNoConsesus(self):
        # print("Running without consensus")
        t1 = time.time()
        global peers
        global blockContext
        devPubKey = getBlockFromSyncList()
        #verififyKeyContext()
        blockContext = "0001"
        #@TODO define somehow a device is in a context
        newBlock = ChainFunctions.createNewBlock(devPubKey, gwPvt, blockContext, consensus)
        signature = verifyBlockCandidate(newBlock, gwPub, devPubKey, peers)
        if (signature == False):
            # logger.info("Consesus was not achieved: block #" +
            #             str(newBlock.index) + " will not be added")
            return False
        ChainFunctions.addBlockHeader(newBlock)
        sendBlockToPeers(newBlock)
        t2 = time.time()
        logger.info("gateway;" + gatewayName + ";" + consensus + ";T5;Time to add a new block with none consensus algorithm;" + '{0:.12f}'.format((t2 - t1) * 1000))
        # print("Finish adding Block without consensus in: "+ '{0:.12f}'.format((t2 - t1) * 1000))
        return True

    def lockForConsensus(self):
        """ lock the consensusLock without resulting in deadlocks """

        global consensusLock
        global peers

        counter = 0
        while (counter < len(peers)):
            while (consensusLock.acquire(
                    False) == False):  # in this mode (with False value) it will lock the execution and return true if it was locked or false if not
                # logger.info("I can't lock my lock, waiting for it")
                time.sleep(0.01)
            # print("##Before for and after acquire my lock")
            for p in peers:
                obj = p.object
                thisPeerIsNotAvailableToLock = obj.acquireLockRemote()
                counter = counter + 1
                # print("On counter = "+str(counter)+" lock result was: "+str(thisPeerIsNotAvailableToLock))
                if (thisPeerIsNotAvailableToLock == False):
                    counter = counter - 1  # I have to unlock the locked ones, the last was not locked
                    # logger.info("Almost got a deadlock")
                    consensusLock.release()
                    if (counter > 0):
                        for p in peers:
                            obj = p.object
                            obj.releaseLockRemote()
                            # logger.info("released lock counter: " + str(counter))
                            counter = counter - 1
                            if (counter == 0):
                                # logger.info("released locks")
                                break
                            # print("After first break PBFT")
                            # logger.info("After first break PBFT")
                    # logger.info("sleeping 0.01")
                    time.sleep(0.01)
                    break
        return True

    def releaseLockForConsensus(self):
        """ lock the consensusLock without resulting in deadlocks """

        global consensusLock
        consensusLock.release()


    # def voteNewOrchestratorExposed(self):
    #     global myVoteForNewOrchestrator
    #     global votesForNewOrchestrator
    #
    #     randomGw = random.randint(0, len(peers) - 1)
    #     votedpubKey = peers[randomGw].object.getGwPubkey()
    #     # print("Selected Gw is: " + str(randomGw))
    #     # print("My pubKey:"+ str(gwPub))
    #     print("VotedpubKey: " + str(votedpubKey))
    #     myVoteForNewOrchestrator = [gwPub, votedpubKey,
    #                                 CryptoFunctions.signInfo(gwPvt, votedpubKey)]  # not safe sign, just for test
    #     votesForNewOrchestrator.append(myVoteForNewOrchestrator)
    #     pickedVote = pickle.dumps(myVoteForNewOrchestrator)
    #     for count in range(0, (len(peers))):
    #         # print("testing range of peers: "+ str(count))
    #         # if(peer != peers[0]):
    #         obj = peers[count].object
    #         obj.addVoteOrchestrator(pickedVote)
    #     return True
    #     # print(str(myVoteForNewOrchestrator))

    # NEW CONSENSUS @Roben

    def verifyBlockCandidateRemote(self, newBlock, askerPubKey):
        """ Receive a new block and verify if it's authentic\n
            @param newBlock - BlockHeader object\n
            @param askerPubKey - Public from the requesting peer\n
            @return True - the block is valid\n
            @return False - the block is not valid
        """
        global peers
        newBlock = pickle.loads(newBlock)
        print("inside verifyblockcandidateremote")
        # logger.debug("|---------------------------------------------------------------------|")
        # logger.debug("Verify for newBlock asked - index:"+str(newBlock.index))
        ret = verifyBlockCandidate(
            newBlock, askerPubKey, newBlock.publicKey, peers)
        # logger.debug("validation reulsts:"+str(ret))
        # logger.debug("|---------------------------------------------------------------------|")
        # pi = pickle.dumps(ret)
        return ret

    def addVoteBlockPBFTRemote(self, newBlock, voterPub, voterSign):
        """ add the signature of a peer into the newBlockCandidate,
            using a list to all gw for a single hash,
            if the block is valid put the signature\n

            @param newBlock - BlockHeader object\n
            @param voterPub - Public key from the voting peer\n
            @param voterSign - new block sign key\n
            @return True - addVoteBlockPFDT only return
        """
        # logger.debug("Received remote add vote...")
        return addVoteBlockPBFT(newBlock, voterPub, voterSign)

    def calcBlockPBFTRemote(self, newBlock):
        """ Calculates if PBFT consensus are achived for the block\n
            @param newBlock - BlockHeader object\n
            @return boolean - True for consensus achived, False if it's not.
        """
        # logger.debug("Received remote calcBlock called...")
        global peers
        return calcBlockPBFT(newBlock, peers)

    def getGwPubkey(self):
        """ Return the peer's public key\n
            @return str - public key
        """
        global gwPub
        return gwPub

    def isBlockInTheChain(self, devPubKey):
        """ Verify if a block is on the chain\n
            @param devPubKey - block pub key\n
            @return boolean - True: block found, False: block not found
        """
        blk = ChainFunctions.findBlock(devPubKey)
        # print("Inside inBlockInTheChain, devPumyVoteForNewOrchestratorbKey= " + str(devPubKey))
        if(blk == False):
            # logger.debug("Block is false="+str(devPubKey))
            return False
        else:
            return True


##############################Smart Contracts####################
    def callEVM(self, dumpedType, dumpedData, dumpedFrom, dumpedDest,dumedSignedDatabyDevice,dumpedDevPubKey):
        """ Call a Ethereum Virtual Machine and use a pre-defined set of parameters\n
            @param tipo - type of the call, can be Execute, Create or Call\n
            @param data - It is the binary data of the contract\n
            @param origin - from account\n
            @param dest - destination account\n
            @signedDatabyDevice - device signature for concat tipo,data,origin and dest
            @devPubKey - to verify signature
        """
        # Create a TCP
        # IP socket

        tipo = pickle.loads(dumpedType)
        data = pickle.loads(dumpedData)
        origin = pickle.loads(dumpedFrom)
        dest = pickle.loads(dumpedDest)
        signedDatabyDevice=pickle.loads(dumedSignedDatabyDevice)
        devPubKey = pickle.loads(dumpedDevPubKey)


        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # Coleta o data da ultima transacao um json
        scBlock = ChainFunctions.findBlock(devPubKey)
        ultimaTrans = ChainFunctions.getLatestBlockTransaction(scBlock).data.strInfoData()
        ultimaTransJSON = json.loads(ultimaTrans)
        transAtual = json.loads(
            '{"Tipo":"%s","Data":"%s","From":"%s","To":"%s"}' % (tipo, data, origin, dest))

        chamada = '{"Tipo":"%s","Data":"%s","From":"%s","To":"%s","Root":"%s"}' % (
            transAtual['Tipo'], transAtual['Data'], transAtual['From'], transAtual['To'], ultimaTransJSON['Root'])
        # chamada =  '{"Tipo":"%s","Data":"%s","From":null,"To":null,"Root":"%s"}' % (transAtual['Tipo'], transAtual['Data'], ultimaTransJSON['Root'])
        chamadaJSON = json.loads(chamada)
        print("antes do try")
        # chamada = '{"Tipo":"Exec","Data":"YAFgQFNgAWBA8w==","From":null,"To":null,"Root":null}'  # Comentar
        # chamadaJSON = json.loads(chamada)  # Comentar
        try:
            # Tamanho maximo do JSON 6 caracteres
            print("AQUI 00001")
            s.connect(('localhost', 6666))
            print("AQUI 000016666")
            tamanhoSmartContract = str(len(chamada))
            for i in range(6 - len(tamanhoSmartContract)):
                tamanhoSmartContract = '0' + tamanhoSmartContract
            # print("Enviando tamanho " + tamanhoSmartContract + "\n")
            # Envia o SC
            print("AQUI 00002")
            s.send(tamanhoSmartContract)
            time.sleep(1)
            # print(json.dumps(chamadaJSON))
            s.send(chamada)
            print("AQUI 000003")
            # Recebe tamanho da resposta
            tamanhoResposta = s.recv(6)
            # print("Tamanho da resposta: " + tamanhoResposta)
            # Recebe resposta
            resposta = s.recv(int(tamanhoResposta))
            # print(resposta + "\n")
            print("AQUI 1")
            # Decodifica resposta
            respostaJSON = json.loads(resposta)
            # print(respsotaJSON['Ret'])
            if respostaJSON['Erro'] != "":
                logger.Exception("Transacao nao inserida")
            elif chamadaJSON['Tipo'] == "Exec":
                print("AQUI 2")
                logger.info("Execucao, sem insercao de dados na blockchain")
            else:
                transacao = '{ "Tipo" : "%s", "Data": "%s", "From": "%s", "To" : "%s", "Root" : "%s" }' % (
                    chamadaJSON['Tipo'], chamadaJSON['Data'], chamadaJSON['From'], chamadaJSON['To'],
                    respostaJSON['Root'])
                logger.info("Transacao sendo inserida: %s \n" % transacao)
                t = ((time.time() * 1000) * 1000)
                timeStr = "{:.0f}".format(t)
                data = timeStr + transacao+signedDatabyDevice
                signedData = CryptoFunctions.signInfo(gwPvt, data)
                logger.debug("###Printing Signing Smart Contract Data before sending: " + signedData)
                #print("I am Here before SC")
                self.addTransactionSC2(transacao, signedDatabyDevice, devPubKey, timeStr)
            # pass

        finally:
            # print("fim\n")
            s.close()
        return True

def addNewBlockToSyncList(devPubKey):
    """ Add a new block to a syncronized list through the peers\n
        @param devPubKey - Public key of the block
    """
    # logger.debug("running critical stuffff......")
    # print("Inside addNewBlockToSyncLIst")
    global lock
    lock.acquire(1)
    # logger.debug("running critical was acquire")
    global blockConsensusCandidateList
    # logger.debug("Appending block to list :")#+srt(len(blockConsensusCandidateList)))
    # print("Inside Lock")
    blockConsensusCandidateList.append(devPubKey)
    lock.release()
    # print("Unlocked")

def getBlockFromSyncList():
    """ Get the first block at a syncronized list through the peers\n
        @return devPubKey - Public key from the block
    """
    # logger.debug("running critical stuffff to get sync list......")
    global lock
    lock.acquire(1)
    # logger.debug("lock aquired by get method......")
    global blockConsensusCandidateList
    if(len(blockConsensusCandidateList) > 0):
        # logger.debug("there is a candidade, pop it!!!")
        devPubKey = blockConsensusCandidateList.pop(0)
    lock.release()
    # logger.debug("Removing block from list :")#+srt(len(blockConsensusCandidateList)))
    return devPubKey

# @Roben returning the peer that has a specified PK

def getPeerbyPK(gwPubKey):
    """ Receive the peer URI generated automatically by pyro4 and return the peer object\n
        @param publicKey publicKey from the peer wanted\n
        @return p - peer object \n
        @return False - peer not found
    """
    global peers
    for p in peers:
        obj = p.object
        # print("Object GW PUB KEY: " + obj.getGwPubkey())
        if obj.getGwPubkey() == gwPubKey:
            return p.peerURI
    return False

###########
# Consensus PBFT @Roben
###########
# the idea newBlockCandidate[newBlockHash][gwPubKey] = signature, if the gateway put its signature, it is voting for YES
newBlockCandidate = {}
newTransactionCandidate = {}  # same as block, for transaction

# def runPBFT():
#     """ Run the PBFT consensus to add a new block on the chain """
#     # print("I am in runPBFT")
#     t1 = time.time()
#     global gwPvt
#     devPubKey = getBlockFromSyncList()
#
#     blk = ChainFunctions.createNewBlock(devPubKey, gwPvt,consensus)
#     # logger.debug("Running PBFT function to block("+str(blk.index)+")")
#
#     PBFTConsensus(blk, gwPub, devPubKey)
#     t2 = time.time()
#     logger.info("=====6=====>time to execute block consensus: " + '{0:.12f}'.format((t2 - t1) * 1000))
#     print("I finished runPBFT")

# def rundBFT():
#     """ Run the PBFT consensus to add a new block on the chain """
#     # print("I am in rundBFT")
#     t1 = time.time()
#     global gwPvt
#     devPubKey = getBlockFromSyncList()
#
#     blk = ChainFunctions.createNewBlock(devPubKey, gwPvt,consensus)
#     # logger.debug("Running PBFT function to block("+str(blk.index)+")")
#     PBFTConsensus(blk, gwPub, devPubKey)
#     t2 = time.time()
#     logger.info("=====6=====>time to execute block consensus: " + '{0:.12f}'.format((t2 - t1) * 1000))
#     print("I finished rundBFT")

def preparePBFTConsensus():
    """ verify all alive peers that will particpate in consensus\n
        @return list of available peers
    """
    alivePeers = []
    global peers
    for p in peers:
        # if p.peerURI._pyroBind(): #verify if peer is alive
        alivePeers.append(p.peerURI)
    # return alivePeers
    return peers

######PBFT Consensus for blocks########

def PBFTConsensus(newBlock, generatorGwPub, generatorDevicePub):
    """ Make the configurations needed to run consensus and call the method runPBFT()\n
        @param newBlock - BlockHeader object\n
        @param generatorGwPub - Public key from the peer who want to generate the block\n
        @param generatorDevicePub - Public key from the device who want to generate the block\n
    """
    global peers
    threads = []
    # logger.debug("newBlock received for PBFT Consensus")
    # connectedPeers = preparePBFTConsensus() #verify who will participate in consensus
    connectedPeers = peers
    # send the new block to the peers in order to get theirs vote.
    # commitBlockPBFT(newBlock, generatorGwPub,generatorDevicePub,connectedPeers) #send to all peers and for it self the result of validation

    # t = threading.Thread(target=commitBlockPBFT, args=(newBlock,generatorGwPub,generatorDevicePub,connectedPeers))
    # t.start()
    print("inside PBFTConsensus, before commitblockpbft")
    commitBlockPBFT(newBlock, generatorGwPub,
                    generatorDevicePub, connectedPeers)
    print("inside PBFTConsensus, after commitblockpbft")
    # threads.append(t)
    # for t in threads:
    #     t.join()

    # if calcBlockPBFT(newBlock,connectedPeers):  # calculate, and if it is good, insert new block and call other peers to do the same
    #     for p in connectedPeers:
    #         # logger.debug("calling to:"+str(p.peerURI))
    #         x = p.object.calcBlockPBFTRemote(newBlock)
    #         # logger.debug("return from peer:"+str(x))
    #     #     t = threading.Thread(target=p.object.calcBlockPBFTRemote, args=(newBlock, connectedPeers))
    #     #     t.start()
    #     #     threads.append(t)
    #     # for t in threads:
    #     #     t.join()
    #     blkHash = CryptoFunctions.calculateHashForBlock(newBlock)
    #     if(blkHash in newBlockCandidate):
    #         del newBlockCandidate[blkHash]
    #     #del newBlockCandidate[CryptoFunctions.calculateHashForBlock(newBlock)]
    #         return True
    # return False

def commitBlockPBFT(newBlock, generatorGwPub, generatorDevicePub, alivePeers):
    """ Send a new block for all the available peers on the network\n
        @param newBlock - BlockHeader object\n
        @param generatorGwPub - Public key from the peer who want to generate the block\n
        @param generatorDevicePub - Public key from the device who want to generate the block\n
    """
    global blockContext
    threads = []
    nbc = ""
    pbftFinished = True
    i = 0
    print("inside commitblockpbft")
    while (pbftFinished and i < 20):
        print("inside commitblockpbft, inside while")
        pbftAchieved = handlePBFT(newBlock, generatorGwPub, generatorGwPub, alivePeers)
        if(not pbftAchieved):
            oldId = newBlock.index
            # logger.info("PBFT not achieve, Recreating block="+ str(ChainFunctions.getBlockchainSize()))
            newBlock = ChainFunctions.createNewBlock(generatorDevicePub, gwPvt, blockContext, consensus)
            # logger.info("Block Recriated ID was:("+str(oldId)+") new:("+str(newBlock.index)+")")
            i = i + 1
            # print("####not pbftAchieved")
        else:
            pbftFinished = False
            # print("####pbftFinished")

    # if (hashblk in newBlockCandidate) and (newBlockCandidate[hashblk] == CryptoFunctions.signInfo(gwPvt, newBlock)):
        # if newBlockCandidate[CryptoFunctions.calculateHashForBlock(newBlock)][gwPub] == CryptoFunctions.signInfo(gwPvt, newBlock):#if it was already inserted a validation for the candidade block, abort
    #    print ("block already in consensus")
    #    return
        # newBlock,generatorGwPub,generatorDevicePub,alivePeers
    # if verifyBlockCandidate(newBlock, generatorGwPub, generatorDevicePub, alivePeers):#verify if the block is valid
    #     for p in alivePeers: #call all peers to verify if block is valid
    #         t = threading.Thread(target=p.object.verifyBlockCandidateRemote, args=(pickle.dumps(newBlock),generatorGwPub,generatorDevicePub))
    #         #### @Regio -> would it be better to use "pickle.dumps(newBlock)"  instead of newBlock?
    #         threads.append(t)
    #     #  join threads
    #     for t in threads:
    #         t.join()

def handlePBFT(newBlock, generatorGwPub, generatorDevicePub, alivePeers):
    """ Send the new block to all the peers available to be verified\n
        @param newBlock - BlockHeader object\n
        @param generatorGwPub - Public key from the peer who want to generate the block\n
        @param generatorDevicePub - Public key from the device who want to generate the block\n
        @param alivePeers - list of available peers\n
        @return boolean - True: block sended to all peers, False: fail to send the block
    """
    hashblk = CryptoFunctions.calculateHashForBlock(newBlock)
    print("inside handlepbft")
    # logger.debug("Running commit function to block: "+str(hashblk))
    # print("######before handlePBFT first for")
    for p in alivePeers:
        # logger.debug("Asking for block verification from: "+str(p.peerURI))
        # verifyRet = p.object.verifyBlockCandidateRemote(pickle.dumps(newBlock), generatorGwPub, generatorDevicePub)
        picked = pickle.dumps(newBlock)
        verifyRet = p.object.verifyBlockCandidateRemote(
            picked, generatorGwPub)
        # logger.debug("Answer received: "+str(verifyRet))
        print("######inside handlePBFT first for")
        if(verifyRet):
            peerPubKey = p.object.getGwPubkey()
            # logger.debug("Pub Key from gateway that voted: "+str(peerPubKey))
            # logger.debug("Running the add vote to block")
            addVoteBlockPBFT(newBlock, peerPubKey, verifyRet)
            calcRet = calcBlockPBFT(newBlock, alivePeers)
            # logger.debug("Result from calcBlockPBFT:"+str(calcRet))
            if(calcRet):
                # logger.info("Consensus was achieve, updating peers and finishing operation")
                sendBlockToPeers(newBlock)
                print("handlePBFT = true")
                return True
    # logger.info("Consesus was not Achieved!!! Block(" +
    #             str(newBlock.index)+") will not added")
    # print("handlePBFT = false")
    return False

# @Roben dbft
# def handledBFT(newBlock,generatorGwPub,generatorDevicePub,alivePeers):
#     """ Send the new block to all the peers available to be verified\n
#         @param newBlock - BlockHeader object\n
#         @param generatorGwPub - Public key from the peer who want to generate the block\n
#         @param generatorDevicePub - Public key from the device who want to generate the block\n
#         @param alivePeers - list of available peers\n
#         @return boolean - True: block sended to all peers, False: fail to send the block
#     """
#     hashblk = CryptoFunctions.calculateHashForBlock(newBlock)
#     # logger.debug("Running commit function to block: "+str(hashblk))
#     #@Roben for p in aliverPeers and p is a delegate
#     for p in alivePeers:
#         # logger.debug("Asking for block verification from: "+str(p.peerURI))
#         #verifyRet = p.object.verifyBlockCandidateRemote(pickle.dumps(newBlock), generatorGwPub, generatorDevicePub)
#         picked = pickle.dumps(newBlock)
#         verifyRet = p.object.verifyBlockCandidateRemote(picked, generatorGwPub)
#         # logger.debug("Answer received: "+str(verifyRet))
#         if(verifyRet):
#             peerPubKey = p.object.getGwPubkey()
#             # logger.debug("Pub Key from gateway that voted: "+str(peerPubKey))
#             # logger.debug("Running the add vote to block")
#             addVoteBlockPBFT(newBlock, peerPubKey, verifyRet)
#             calcRet = calcBlockPBFT(newBlock, alivePeers)
#             # logger.debug("Result from calcBlockPBFT:"+str(calcRet))
#             if(calcRet):
#                 logger.info("Consensus was achieve, updating peers and finishing operation")
#                 sendBlockToPeers(newBlock)
#                 return True
#     logger.info("Consesus was not Achieved!!! Block("+str(newBlock.index)+") will not added")
#     return False

def verifyBlockCandidate(newBlock, generatorGwPub, generatorDevicePub, alivePeers):
    """ Checks whether the new block has the following characteristics: \n
        * The hash of the previous block are correct in the new block data\n
        * The new block index is equals to the previous block index plus one\n
        * The generation time of the last block is smaller than the new one \n
        If the new block have it all, sign it with the peer private key\n
        @return False - The block does not have one or more of the previous characteristics\n
        @return voteSignature - The block has been verified and approved
    """
    blockValidation = True
    lastBlk = ChainFunctions.getLatestBlock()
    # logger.debug("last block:"+str(lastBlk.strBlock()))
    lastBlkHash = CryptoFunctions.calculateHashForBlock(lastBlk)
    # print("Index:"+str(lastBlk.index)+" prevHash:"+str(lastBlk.previousHash)+ " time:"+str(lastBlk.timestamp)+ " pubKey:")
    # lastBlkHash = CryptoFunctions.calculateHash(lastBlk.index, lastBlk.previousHash, lastBlk.timestamp,
    #                                             lastBlk.publicKey)
    # print ("This Hash:"+str(lastBlkHash))
    # print ("Last Hash:"+str(block.previousHash))

    if (lastBlkHash != newBlock.previousHash):
        print("validation lastblkhash")
        logger.error("Failed to validate new block(" +
                        str(newBlock.index)+") HASH value")
        # logger.debug("lastBlkHash="+str(lastBlkHash))
        # logger.debug("newBlock-previousHash="+str(newBlock.previousHash))
        blockValidation = False
        return blockValidation
    if (int(lastBlk.index+1) != int(newBlock.index)):
        print("validation lastblkindex")
        logger.error("Failed to validate new block(" +
                        str(newBlock.index)+") INDEX value")
        # logger.debug("lastBlk Index="+str(lastBlk.index))
        # logger.debug("newBlock Index="+str(newBlock.index))
        blockValidation = False
        return blockValidation
    if (lastBlk.timestamp >= newBlock.timestamp):
        print("validation lastblktime")
        logger.error("Failed to validate new block(" +
                        str(newBlock.index)+") TIME value")
        # logger.debug("lastBlk time:"+str(lastBlk.timestamp))
        # logger.debug("lastBlk time:"+str(newBlock.timestamp))
        blockValidation = False
        return blockValidation
    if blockValidation:
        # logger.info("block successfully validated")
        voteSignature = CryptoFunctions.signInfo(
            gwPvt, newBlock.__str__())  # identify the problem in this line!!
        # logger.debug("block successfully signed")
        # addVoteBlockPBFT(newBlock, gwPub, voteSignature)
        # logger.debug("block successfully added locally")
        return voteSignature
        # addVoteBlockPBFT(newBlock, gwPub, voteSignature) #vote positively, signing the candidate block
        # for p in alivePeers:
        #     p.object.addVoteBlockPBFTRemote(newBlock, gwPub, voteSignature) #put its vote in the list of each peer
        # return True
    else:
        print("Failed to validate new block")
        logger.error("Failed to validate new block")
        return False

def addVoteBlockPBFT(newBlock, voterPub, voterSign):
    """ add the signature of a peer into the newBlockCandidate,
        using a list to all gw for a single hash, if the block is valid put the signature \n
        @return True -  why not ? :P   ... TODO why return
    """
    global newBlockCandidate
    blkHash = CryptoFunctions.calculateHashForBlock(newBlock)
    # logger.debug("Adding the block to my local dictionary")
    if(blkHash not in newBlockCandidate):
        # logger.debug("Block is not in the dictionary... creating a new entry for it")
        newBlockCandidate[blkHash] = {}
    newBlockCandidate[blkHash][voterPub] = voterSign
    # print("vote added")
    # newBlockCandidate[CryptoFunctions.calculateHashForBlock(newBlock)][voterPub] = voterSign
    return True

def calcBlockPBFT(newBlock, alivePeers):
    """ Verify if the new block achieved the consensus\n
        @param newBlock - BlockHeader object\n
        @param alivePeers - list of available peers\n
        @return boolean - True: consensus achived, False: consensus Not achieved yet
    """
    # print("Inside CalcBlockPBFT")
    # print("Consensus:   "+ consensus)
    # if (consensus=="PoW"):
    #     return True
    # logger.debug("Running the calc blockc pbft operation")
    blHash = CryptoFunctions.calculateHashForBlock(newBlock)
    locDicCount = int(len(newBlockCandidate[blHash]))
    peerCount = int(len(alivePeers))
    # logger.debug("local dictionary value:"+str(locDicCount))
    # logger.debug("alivePeers: "+str(peerCount))
    # cont=0
    if(consensus == "PBFT" or consensus == "dBFT"):
        cont = int(float(0.667)*float(peerCount))
    if(consensus == "Witness3"):
        cont = 2
    # print("##Value of cont:   "+str(cont))
    # if len(newBlockCandidate[CryptoFunctions.calculateHashForBlock(newBlock)]) > ((2/3)*len(alivePeers)):
    if (blHash in newBlockCandidate) and (locDicCount >= cont):
        # logger.debug("Consensus achieved!")
        ChainFunctions.addBlockHeader(newBlock)
        # for p in alivePeers:
        #     p.object.insertBlock(blkHash)
        # print("calcBLockPBFT = True")
        return True
    else:
        # logger.debug("Consensus Not achieved yet!")
        # print("calcBLockPBFT = false")
        return False

######
# Transaction PBFT
######

# Consensus for transactions
def PBFTConsensusTransaction(block, newTransaction, generatorGwPub, generatorDevicePub):
    """ Run the PBFT consensus to add a new transaction to a block\n
        @param block - BlockHeader object where the transaction will be add\n
        @param newTransaction - the transaction who will be add\n
        @param generatorGwPub - Sender peer public key\n
        @generatorDevicePub - Device how create the transaction and wants to add it to a block\n
        @return boolean - True: Transaction approved to consensus, False: transaction not approved
    """
    threads = []
    connectedPeers = preparePBFTConsensus()
    commitTransactionPBFT(block, newTransaction,
                            generatorGwPub, generatorDevicePub, connectedPeers)
    # calculate, and if it is good, insert new block and call other peers to do the same
    if calcTransactionPBFT(newTransaction, connectedPeers):
        for p in connectedPeers:
            t = threading.Thread(target=p.object.calcBlockPBFT, args=(
                block, newTransaction, connectedPeers))
            threads.append(t)
        for t in threads:
            t.join()
        del newBlockCandidate[CryptoFunctions.calculateHashForBlock(
            newTransaction)]
        return True
    return False

def commitTransactionPBFT(block, newTransaction, generatorGwPub, generatorDevicePub, alivePeers):
    """ Send a transaction to be validated by all peers\n
        @param block - BlockHeader object where the transaction will be add\n
        @param newTransaction - the transaction who will be add\n
        @param generatorGwPub - Sender peer public key\n
        @generatorDevicePub - Device how create the transaction and wants to add it to a block\n
        @param alivePeers - list of available peerszn\n
        @return boolean - True: sended to validation, False: transaction are not valid or already in consensus
    """
    # TODO similar to what was done with block, just different verifications
    threads = []
    # if it was already inserted a validation for the candidade block, abort
    if newTransactionCandidate[CryptoFunctions.calculateHash(newTransaction)][gwPub] == CryptoFunctions.signInfo(gwPvt, newTransaction):
        # print ("transaction already in consensus")
        return False
    if verifyTransactionCandidate():  # verify if the transaction is valid
        for p in alivePeers:  # call all peers to verify if block is valid
            t = threading.Thread(target=p.object.verifyTransactionCandidate, args=(
                block, newTransaction, generatorGwPub, generatorDevicePub, alivePeers))
            # @Regio -> would it be better to use "pickle.dumps(newBlock)"  instead of newBlock?
            threads.append(t)
        #  join threads
        for t in threads:
            t.join()
        return True
    return False

def verifyTransactionCandidate(block, newTransaction, generatorGwPub, generatorDevicePub, alivePeers):
    """ Checks whether the new transaction has the following characteristics:\n
        * The block is on the chain\n
        * The last transaction hash on the chain and the new transaction are the same\n
        * The index of the new transaction are the index of the last transaction plus one\n
        * The generation time of the last transaction is smaller than the new one \n
        * The data is sign by the TODO (generator device or gateway)
        @param block - BlockHeader object where the transaction will be add\n
        @param newTransaction - the transaction who will be add\n
        @param generatorGwPub - Sender peer public key\n
        @generatorDevicePub - Device how create the transaction and wants to add it to a block\n
        @param alivePeers - list of available peers\n
        @return boolean - True: approved, False: not approved
    """
    transactionValidation = True
    if (ChainFunctions.getBlockByIndex(block.index)) != block:
        transactionValidation = False
        return transactionValidation

    #lastTransaction = ChainFunctions.getLatestBlockTransaction(block)
    # print("Index:"+str(lastBlk.index)+" prevHash:"+str(lastBlk.previousHash)+ " time:"+str(lastBlk.timestamp)+ " pubKey:")
    #lastTransactionHash = CryptoFunctions.calculateHash(lastTransaction.index, lastTransaction.previousHash, lastTransaction.timestamp, lastTransaction.data, lastTransaction.signature, lastTransaction.signature)
    lastTransactionHash = CryptoFunctions.calculateTransactionHash(ChainFunctions.getLatestBlockTransaction(block))

    # print ("This Hash:"+str(lastBlkHash))
    # print ("Last Hash:"+str(block.previousHash))
    if (lastTransactionHash != newTransaction.previousHash):
        transactionValidation = False
        return transactionValidation
    if (newTransaction.index != (lastTransactionHash.index+1)):
        transactionValidation = False
        return transactionValidation
    if (lastTransaction.timestamp <= newTransaction.timestamp):
        transactionValidation = False
        return transactionValidation
    # @Regio the publick key used below should be from device or from GW?
    if not (CryptoFunctions.signVerify(newTransaction.data, newTransaction.signature, generatorDevicePub)):
        transactionValidation = False
        return transactionValidation
    if transactionValidation:
        voteSignature = CryptoFunctions.signInfo(gwPvt, newTransaction)
        # vote positively, signing the candidate transaction
        addVoteTransactionPBFT(newTransaction, gwPub, voteSignature)
        for p in alivePeers:
            # put its vote in the list of each peer
            p.object.addVoteBlockPBFT(newTransaction, gwPub, voteSignature)
        return True
    else:
        return False

def addVoteTransactionPBFT(newTransaction, voterPub, voterSign):
    """ Add the vote of the peer to the transaction\n
        @param newTransaction - Transaction object\n
        @param voterPub - vote of the peer\n
        @param voterSing - sing of the peer\n
        @return True TODO needed?
    """
    global newTransactionCandidate
    newTransactionCandidate[CryptoFunctions.calculateHashForBlock(
        newTransaction)][voterPub] = voterSign
    return True

def calcTransactionPBFT(block, newTransaction, alivePeers):
    """ If consensus are achivied, add the transaction to the block\n
        @param block - BlockHeader object where the transaction will be add\n
        @param newTransaction - the transaction who will be add\n
        @param alivePeers - list of available peers\n
        @return True TODO needed?
    """
    if len(newTransactionCandidate[CryptoFunctions.calculateHash(newTransaction)]) > ((2/3)*len(alivePeers)):
        ChainFunctions.addBlockTransaction(block, newTransaction)
    return True
# Consensus PBFT END

# ################Consensus PoW
# def runPoW():
#     """ Run the PoW consensus to add a new block on the chain """
#     print("I am in runPoW")
#     t1 = time.time()
#     global gwPvt
#     devPubKey = getBlockFromSyncList()
#     blk = ChainFunctions.createNewBlock(devPubKey, gwPvt, consensus)
#     print("Device PubKey (insire runPoW): " + str(devPubKey))
#
#     if(PoWConsensus(blk, gwPub, devPubKey)):
#         t2 = time.time()
#         logger.info("=====6=====>time to execute PoW block consensus: " + '{0:.12f}'.format((t2 - t1) * 1000))
#         print("I finished runPoW")
#     else:
#         t2 = time.time()
#         logger.info("Something went wrong, time to execute PoW Block Consensus" + '{0:.12f}'.format((t2 - t1) * 1000))
#         print("I finished runPoW - Wrong")

def PoWConsensus(newBlock, generatorGwPub, generatorDevicePub):
    """ Make the configurations needed to run consensus and call the method runPBFT()\n
        @param newBlock - BlockHeader object\n
        @param generatorGwPub - Public key from the peer who want to generate the block\n
        @param generatorDevicePub - Public key from the device who want to generate the block\n
    """
    global peers
    # logger.debug("newBlock received for PoW Consensus")
    signature = verifyBlockCandidate(
        newBlock, generatorGwPub, generatorDevicePub, peers)
    if (signature == False):
        # logger.info("Consesus was not Achieved!!! Block(" + str(newBlock.index) + ") will not added")
        return False
    addVoteBlockPoW(newBlock, generatorGwPub, signature)
    # logger.info("Consensus was achieve, updating peers and finishing operation")
    ChainFunctions.addBlockHeader(newBlock)
    sendBlockToPeers(newBlock)

    return True

def addVoteBlockPoW(newBlock, voterPub, voterSign):
    """ add the signature of a peer into the newBlockCandidate,
        using a list to all gw for a single hash, if the block is valid put the signature \n
        @return True -  why not ? :P   ... TODO why return
    """
    global newBlockCandidate
    blkHash = CryptoFunctions.calculateHashForBlock(newBlock)
    # logger.debug("Adding the block to my local dictionary")
    if(blkHash not in newBlockCandidate):
        # logger.debug("Block is not in the dictionary... creating a new entry for it")
        newBlockCandidate[blkHash] = {}
    newBlockCandidate[blkHash][voterPub] = voterSign
    # print("PoW vote added")
    # newBlockCandidate[CryptoFunctions.calculateHashForBlock(newBlock)][voterPub] = voterSign
    return True

#############################################################################
#############################################################################
######################          Main         ################################
#############################################################################
#############################################################################

# @Roben update to load orchestrator by block index
# get first gw pkey


def loadOrchestratorIndex(index):
    global orchestratorObject
    orchestratorGWblock = ChainFunctions.getBlockByIndex(index)
    orchestratorGWpk = orchestratorGWblock.publicKey
    # print("Public Key inside loadOrchestratorINdex: " + orchestratorGWpk)
    if (orchestratorGWpk == gwPub):  # if I am the orchestrator, use my URI
        uri = myURI
    else:
        uri = getPeerbyPK(orchestratorGWpk)
    # print("loading orchestrator URI: " + uri)
    orchestratorObject = Pyro4.Proxy(uri)
    # return orchestratorObject


def loadOrchestratorFirstinPeers():
    global orchestratorObject
    if(len(peers) < 1):
        uri = myURI
        orchestratorObject = Pyro4.Proxy(uri)
        # logger.info("I am my own orchestrator....")
    else:
        # print("First peer is"+ peers[0].peerURI)
        # uri=peers[0].peerURI
        obj = peers[0].object
        dat = pickle.loads(obj.getMyOrchestrator())
        # print("##My Orchestrator orchestrator: "+str(dat))
        # logger.info("##My Orchestrator orchestrator: "+str(dat))
        orchestratorObject = dat
    # orchestratorObject = Pyro4.Proxy(uri)
    # if (orchestratorGWpk == gwPub): #if I am the orchestrator, use my URI
    #     uri=myURI
    # else:from Crypto import Random
    #     uri = getPeerbyPK(orchestratorGWpk)
    # print("loading orchestrator URI: " + uri)
    # orchestratorObject=Pyro4.Proxy(uri)


def voteNewOrchestrator():
    global myVoteForNewOrchestrator
    global votesForNewOrchestrator
    randomGw = random.randint(0, len(peers) - 1)
    votedURI = peers[randomGw].peerURI
    # print("Selected Gw is: " + str(randomGw))
    # print("My pubKey:"+ str(gwPub))
    # print("votedURI: " + str(votedURI))
    # myVoteForNewOrchestrator = [gwPub, votedURI, CryptoFunctions.signInfo(gwPvt, votedURI)]  # not safe sign, just for test
    myVoteForNewOrchestrator = votedURI
    votesForNewOrchestrator.append(myVoteForNewOrchestrator)
    pickedVote = pickle.dumps(myVoteForNewOrchestrator)
    for count in range(0, (len(peers))):
        # print("testing range of peers: "+ str(count))
        # if(peer != peers[0]):
        obj = peers[count].object
        obj.addVoteOrchestrator(pickedVote)
    # print(str(myVoteForNewOrchestrator))

# @Roben get the next GW PBKEYfrom Crypto import Random
# def setNextOrchestrator(consensus, newOrchestratorIndex):
#     global orchestratorObject
#     if(consensus == 'dBFT'):
#         newOrchestratorbk=ChainFunctions.getBlockByIndex(newOrchestratorIndex)
#         newOrchestratorPK=newOrchestratorbk.publickey
#         uri= getPeerbyPK(newOrchestratorbk)
#         orchestratorObject=Pyro4.Proxy(uri)
#         return orchestratorObject
# ###############################################

# This method "loadOrchestrator() is deprecated... It is not used anymore...


def loadOrchestrator():
    """ Connect the peer to the orchestrator TODO automate connection with orchestrator """
    global orchestratorObject
    # text_file = open("/home/core/nodes/Gw1.txt", "r")#it will add a file to set gw1 as first orchestrator
    text_file = open("/tmp/Gw1.txt", "r")
    uri = text_file.read()
    # print("I load the orchestrator, its URI is: "+uri)
    # print(uri)
    # logger.debug("Orchestrator address loaded")
    orchestratorObject = Pyro4.Proxy(uri)
    text_file.close()


def runMasterThread():
    """ initialize the PBFT of the peer """
    # @Roben atualizacao para definir dinamicamente quem controla a votacao - o orchestrator -
    # global currentOrchestrator
    # while(currentOrchestrator == myURI):
    # print("Inside runMasterThread")
    while(True):
        if (orchestratorObject.exposedURI() == myURI):
            if (consensus == "PoW"):
                if(len(blockConsensusCandidateList) > 0):
                    # print("going to runPoW")
                    runPoW()
            if (consensus == "PBFT"):
                if(len(blockConsensusCandidateList) > 0):
                    # print("going to runPBFT")
                    runPBFT()
            if (consensus == "dBFT" or consensus == "Witness3"):
                if(len(blockConsensusCandidateList) > 0):
                    # print("going to rundBFT")
                    rundBFT()
        time.sleep(1)


def saveOrchestratorURI(uri):
    """ save the uri of the orchestrator\n
        @param uri - orchestrator URI
    """
    # text_file = open("/home/core/nodes/Gw1.txt", "w")
    #text_file = open("/tmp/Gw1.txt", "w")
    # text_file.write(uri)
    # text_file.close()


def saveURItoFile(uri):
    """ Save the peer's URI to a file \n
        @param uri - peers URI
    """
    #fname = socket.gethostname()
    #text_file = open(fname, "w")
    # text_file.write(uri)
    # text_file.close()


""" Main function initiate the system"""


def main():

    global myURI
    global votesForNewOrchestrator

    nameServerIP = sys.argv[1]
    nameServerPort = int(sys.argv[2])
    global gatewayName
    gatewayName = sys.argv[3]

    # initialize Logger
    global logger
    logger = Logger.configure(gatewayName + ".log")

    # create the blockchain
    bootstrapChain2()

    # print ("Please copy the server address: PYRO:chain.server...... as shown and use it in deviceSimulator.py")
    #with Pyro4.Daemon(getMyIP()) as daemon:
    #    myURI = daemon.register(R2ac, gatewayName)
    #    with Pyro4.locateNS(host=nameServerIP, port=nameServerPort) as ns:
    #        ns.register(name=gatewayName, uri=myURI, safe=False)
    #        connectToPeers(ns)
    #        for name, uri in ns.list().items():
    #            logger.info("Peer:" + name + "(" + uri + ")")
    ns = Pyro4.locateNS(host=nameServerIP, port=nameServerPort)
    daemon = Pyro4.Daemon(getMyIP())
    uri = daemon.register(R2ac, gatewayName)
    # uri = daemon.register(R2ac)
    myURI = str(uri)
    ns.register(name=gatewayName, uri=myURI, safe=False)
    # ns.register(myURI, uri, True)
    connectToPeers(ns)
    bcSize = ChainFunctions.getBlockchainSize()
    # logger.debug("Blockchain size = "+ str(bcSize))
    numberConnectedPeers = len(peers)
    # logger.debug("Number of connecter peers = " + str(numberConnectedPeers))
    if(numberConnectedPeers < 1):
        # logger.debug("Starting the first gateway...")
        # saveOrchestratorURI(myURI)
        # logger.info("Creatin thread....")
        # print("going to master thread")
        loadOrchestratorFirstinPeers()
        # firstGwBlock = ChainFunctions.createNewBlock(gwPub, gwPvt, consensus
        # ChainFunctions.addBlockHeader(firstGwBlock)
        # R2ac.updateIOTBlockLedger(firstGwBlock, myName)
        # loadOrchestrator()
        # loadOrchestratorIndex(1)
        # threading.Thread(target=runMasterThread).start()
    else:
        loadOrchestratorFirstinPeers()
        # time.sleep(5)
        # print("inside main else")
        # pickedUri = pickle.dumps(myURI)
        # for peer in peers:
        #     obj = peer.object
        #     print("Before gettin last chain blocks")
        #     obj.getLastChainBlocks(pickedUri, ChainFunctions.getBlockchainSize())
        # # loadOrchestratorIndex(1)
        # if (len(peers)>3):
        #     electNewOrchestor()
        # loadOrchestrator()
        # threading.Thread(target=runMasterThread).start()
        # print("tamanho de todos os votos: "+str(len(votesForNewOrchestrator)))
        # print("after getting last chain blocks")

    logger.info("Running SpeedyCHAIN gateway " + gatewayName + " in " + myURI)
    logger.info("Pyro name server: " + nameServerIP + ":" + str(nameServerPort))

    daemon.requestLoop()


if __name__ == '__main__':
    if len(sys.argv[1:]) < 1:
        print("Command line syntax:")
        print("  python -m Gateway.py <name server IP> <name server port> <gateway name>")
        print("  Pyro name server must be running on <name server IP>:<name server port>")
        print("    Run Pyro4: pyro4-ns -n <name server IP> -p <name server port>")
        quit()
    else:
        main()
