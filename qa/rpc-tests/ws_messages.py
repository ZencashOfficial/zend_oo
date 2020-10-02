#!/usr/bin/env python2
# Copyright (c) 2014 The Bitcoin Core developers
# Copyright (c) 2018 The Zencash developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
from test_framework.test_framework import BitcoinTestFramework
from test_framework.authproxy import JSONRPCException
from test_framework.util import assert_equal, initialize_chain_clean, \
    start_nodes, sync_blocks, sync_mempools, connect_nodes_bi, mark_logs,\
    get_epoch_data, \
    assert_false, assert_true
from test_framework.mc_test.mc_test import *
import os
import json
import pprint
from decimal import Decimal
import threading
import time
from websocket import create_connection
from websocket._exceptions import WebSocketConnectionClosedException

DEBUG_MODE = 1
NUMB_OF_NODES = 3
EPOCH_LENGTH = 5
CERT_FEE = Decimal('0.00015')

def get_epoch_data( scid, node, epochLen):
    sc_creating_height = node.getscinfo(scid)['created at block height']
    current_height = node.getblockcount()
    epoch_number = (current_height - sc_creating_height + 1) // epochLen - 1
    epoch_block_hash = node.getblockhash(sc_creating_height - 1 + ((epoch_number + 1) * epochLen))
    prev_epoch_block_hash = node.getblockhash(sc_creating_height - 1 + ((epoch_number) * epochLen))
    return epoch_block_hash, epoch_number, prev_epoch_block_hash


def ws_client(node, arg):
    wsurl = node.get_wsurl()
    
    if wsurl == None:
        print "###################### no ws conn: exiting"
        return

    print "##### ws client connecting to ws_url {} ######################".format(wsurl)
    ws = create_connection(wsurl)

    t = threading.currentThread()

    while getattr(t, "do_run", True):
        try:
            data = ws.recv()
            if getattr(t, "handle_events", True):
                arg.wsEventPayload = json.loads(data)['eventPayload']
                arg.sem.release()
                print "############ Sem Given"
        except WebSocketConnectionClosedException, e:
            print "############ Server closed connection"
            break
        except Exception, e:
            print "Unexpected exception:  ", str(e)
            break


    print "##### ws client closing".format(wsurl)
    ws.close()

class ws_messages(BitcoinTestFramework):

    alert_filename = None

    def setup_chain(self, split=False):
        print("Initializing test directory " + self.options.tmpdir)
        initialize_chain_clean(self.options.tmpdir, NUMB_OF_NODES)
        self.alert_filename = os.path.join(self.options.tmpdir, "alert.txt")
        with open(self.alert_filename, 'w'):
            pass  # Just open then close to create zero-length file

    def setup_network(self, split=False):
        self.nodes = []

        common_args = [
            '-websocket=1', '-debug=ws',
            '-txindex=1',
#            '-wsport=12345',
#            '-debug=ws',
            '-debug=py', '-debug=sc', '-debug=mempool', '-debug=net',
            '-debug=cert', '-debug=zendoo_mc_cryptolib', '-logtimemicros=1']

        self.nodes = start_nodes(NUMB_OF_NODES, self.options.tmpdir, extra_args = [common_args]*NUMB_OF_NODES)

#        import pdb; pdb.set_trace()
        connect_nodes_bi(self.nodes, 0, 1)
        connect_nodes_bi(self.nodes, 1, 2)
        sync_blocks(self.nodes[1:NUMB_OF_NODES])
        sync_mempools(self.nodes[1:NUMB_OF_NODES])
        self.is_network_split = split
        self.sync_all()

    def run_test(self):

        '''
        Different Websocket messages are tested
        '''

        self.sem = threading.Semaphore()
        self.sem.acquire()
        print "############ Sem Taken"

        t = threading.Thread(target=ws_client, args=(self.nodes[1], self,))
        t.daemon = True         # This thread dies when main thread exits.
        t.handle_events = False # do not handle evt by default
        t.start()

        # forward transfer amounts
        creation_amount = Decimal("0.5")
        fwt_amount = Decimal("50")
        bwt_amount_bad = Decimal("100.0")
        bwt_amount = Decimal("50")

        self.nodes[0].getblockhash(0)

        # node 1 earns some coins, they would be available after 100 blocks
        mark_logs("Node 1 generates 1 block", self.nodes, DEBUG_MODE)
        self.nodes[1].generate(1)
        self.sync_all()

        mark_logs("Node 0 generates 220 block", self.nodes, DEBUG_MODE)
        self.nodes[0].generate(220)
        self.sync_all()

        # SC creation

        #generate wCertVk and constant
        mcTest = MCTestUtils(self.options.tmpdir, self.options.srcdir)
        vk = mcTest.generate_params("sc1")
        constant = generate_random_field_element_hex()

        ret = self.nodes[1].sc_create(EPOCH_LENGTH, "dada", creation_amount, vk, "", constant)
        creating_tx = ret['txid']
        scid = ret['scid']
        mark_logs("Node 1 created the SC spending {} coins via tx {}.".format(creation_amount, creating_tx), self.nodes, DEBUG_MODE)
        mark_logs("created SC id: {}".format(scid), self.nodes, DEBUG_MODE)
        self.sync_all()

        mark_logs("Node0 confirms Sc creation generating 1 block", self.nodes, DEBUG_MODE)
        self.nodes[0].generate(1)
        sc_creating_height = self.nodes[0].getblockcount()
        self.sync_all()

        # Fwd Transfer to Sc
        fwd_tx = self.nodes[0].sc_send("abcd", fwt_amount, scid)
        mark_logs("Node0 transfers {} coins to SC with tx {}...".format(fwt_amount, fwd_tx), self.nodes, DEBUG_MODE)
        self.sync_all()

        mark_logs("Node0 confirms fwd transfer generating 1 block", self.nodes, DEBUG_MODE)
        self.nodes[0].generate(1)
        self.sync_all()

        mark_logs("Node0 generating 3 more blocks to achieve end of withdrawal epoch", self.nodes, DEBUG_MODE)
        self.nodes[0].generate(3)
        self.sync_all()

        epoch_block_hash, epoch_number, prev_epoch_block_hash = get_epoch_data(scid, self.nodes[0], EPOCH_LENGTH)
        mark_logs("epoch_number = {}, epoch_block_hash = {}".format(epoch_number, epoch_block_hash), self.nodes, DEBUG_MODE)

        pkh_node1 = self.nodes[1].getnewaddress("", True)

        #Create proof for WCert
        quality = 0
        proof = mcTest.create_test_proof(
            "sc1", epoch_number, epoch_block_hash, prev_epoch_block_hash,
            quality, constant, [pkh_node1], [bwt_amount])

        epoch_number_0     = epoch_number
        epoch_block_hash_0 = epoch_block_hash

        amount_cert_1 = [{"pubkeyhash": pkh_node1, "amount": bwt_amount}]
        mark_logs("Node 0 performs a bwd transfer to Node1 pkh {} of {} coins via Websocket".format(amount_cert_1[0]["pubkeyhash"], amount_cert_1[0]["amount"]), self.nodes, DEBUG_MODE)
        #----------------------------------------------------------------"
        cert_epoch_0 = self.nodes[1].ws_send_certificate(
            scid, epoch_number, quality, epoch_block_hash, proof, amount_cert_1)
        self.sync_all()

        mark_logs("Check cert is in mempool", self.nodes, DEBUG_MODE)
        assert_equal(True, cert_epoch_0 in self.nodes[0].getrawmempool())

        mark_logs("Node0 generates 1 block, check that Websocket evt is correctly handled ", self.nodes, DEBUG_MODE)
        t.handle_events = True
        bh = self.nodes[0].generate(1)[0]
        self.sync_all()
        while True:
            self.sem.acquire()
            t.handle_events = False
            print "############ Sem Taken"
            break

        bc = self.nodes[0].getblockcount()
        bl = self.nodes[0].getblock(str(bc), False)
        assert_equal(self.wsEventPayload['height'], bc)
        assert_equal(self.wsEventPayload['hash'], bh)
        assert_equal(self.wsEventPayload['block'], bl)

        height_, hash_, block_ = self.nodes[0].ws_get_single_block(bc)
        assert_equal(height_, bc)
        assert_equal(hash_, bh)
        assert_equal(block_, bl)
        '''
        '''

        t.do_run = False
#        t.join()
        return

        #----------------------------------------------------------------"
        '''
        try:
            cert_epoch_0 = self.nodes[0].send_certificate(scid, epoch_number, quality, epoch_block_hash, proof, amount_cert_1, CERT_FEE)
            assert(len(cert_epoch_0) > 0)
            mark_logs("Certificate is {}".format(cert_epoch_0), self.nodes, DEBUG_MODE)
        except JSONRPCException, e:
            errorString = e.error['message']
            mark_logs("Send certificate failed with reason {}".format(errorString), self.nodes, DEBUG_MODE)
            assert(False)
       '''

        mark_logs("Checking mempools alignement", self.nodes, DEBUG_MODE)
        self.sync_all()
        for i in range(1, NUMB_OF_NODES):
            assert_equal(sorted(self.nodes[0].getrawmempool()), sorted(self.nodes[i].getrawmempool()))

        mark_logs("Check cert is in mempools", self.nodes, DEBUG_MODE)
        assert_equal(True, cert_epoch_0 in self.nodes[0].getrawmempool())

        bal_before_bwt = self.nodes[1].getbalance("", 0)
        mark_logs("Node1 balance before bwt is received: {}".format(bal_before_bwt), self.nodes, DEBUG_MODE)

        mark_logs("Node 0 try to generate a second bwd transfer for the same epoch number before first bwd is confirmed", self.nodes, DEBUG_MODE)
        try:
            self.nodes[0].send_certificate(scid, epoch_number, quality, epoch_block_hash, proof, amount_cert_1, CERT_FEE)
            assert(False)
        except JSONRPCException, e:
            errorString = e.error['message']
            mark_logs(errorString, self.nodes, DEBUG_MODE)

        assert_equal("conflicting cert" in errorString, True)

        mark_logs("Node0 confims bwd transfer generating 1 block", self.nodes, DEBUG_MODE)
        mined = self.nodes[0].generate(1)[0]
        self.sync_all()

        mark_logs("Check cert is not in mempool anymore", self.nodes, DEBUG_MODE)
        assert_equal(False, cert_epoch_0 in self.nodes[0].getrawmempool())

        mark_logs("Check block coinbase contains the certificate fee", self.nodes, DEBUG_MODE)
        coinbase = self.nodes[0].getblock(mined, True)['tx'][0]
        decoded_coinbase = self.nodes[2].getrawtransaction(coinbase, 1)
        miner_quota = decoded_coinbase['vout'][0]['value']
        assert_equal(miner_quota, (Decimal('7.5') + CERT_FEE))
        assert_equal(self.nodes[0].getscinfo(scid)['balance'], creation_amount + fwt_amount- amount_cert_1[0]["amount"])
        assert_equal(len(self.nodes[0].getscinfo(scid)['immature amounts']), 0)

        mark_logs("Node 0 tries to performs a bwd transfer for the same epoch number as before...", self.nodes, DEBUG_MODE)
        try:
            self.nodes[0].send_certificate(scid, epoch_number, quality, epoch_block_hash, proof, amount_cert_1, CERT_FEE)
            assert(False)
        except JSONRPCException, e:
            errorString = e.error['message']
            mark_logs(errorString, self.nodes, DEBUG_MODE)

        assert_equal("invalid" in errorString, True)

        mark_logs("Checking that amount transferred by certificate reaches Node1 wallet", self.nodes, DEBUG_MODE)
        retrieved_cert = self.nodes[1].gettransaction(cert_epoch_0)
        assert_equal(retrieved_cert['amount'], 0)  # Certificate amount is not mature yet
        assert_equal(retrieved_cert['details'][0]['category'], "immature")
        assert_equal(retrieved_cert['details'][0]['amount'], amount_cert_1[0]["amount"])

        assert_equal(self.nodes[1].getwalletinfo()['immature_balance'], amount_cert_1[0]["amount"])
        utxos_Node1 = self.nodes[1].listunspent()
        for utxo in utxos_Node1:
            assert_false("cert" in utxo.keys())
            assert_false(utxo["txid"] == cert_epoch_0)

        bal_after_bwt_confirmed = self.nodes[1].getbalance("", 0)
        mark_logs("Node1 balance after bwt is confirmed: {}".format(bal_after_bwt_confirmed), self.nodes, DEBUG_MODE)
        assert_equal(bal_after_bwt_confirmed, bal_before_bwt)  # cert_net_amount is not matured yet.

        mark_logs("Checking that Node1 cannot immediately spend coins received from bwd transfer", self.nodes, DEBUG_MODE)
        mark_logs("Node 1 tries to send {} coins to node2...".format(amount_cert_1[0]["amount"] / 2), self.nodes, DEBUG_MODE)
        try:
            tx = self.nodes[1].sendtoaddress(self.nodes[2].getnewaddress(), amount_cert_1[0]["amount"] / 2)
            assert(len(tx) == 0)
        except JSONRPCException, e:
            errorString = e.error['message']
            mark_logs(errorString, self.nodes, DEBUG_MODE)

        assert_equal("Insufficient funds" in errorString, True)

        mark_logs("Show that coins from bwt can be spent once next epoch certificate is received and confirmed", self.nodes, DEBUG_MODE)
        mark_logs("Node0 generating enough blocks to move to new withdrawal epoch", self.nodes, DEBUG_MODE)
        self.nodes[0].generate(EPOCH_LENGTH - 1)
        self.sync_all()

        prev_epoch_block_hash = epoch_block_hash
        epoch_block_hash, epoch_number = get_epoch_data(scid, self.nodes[0], EPOCH_LENGTH)
        mark_logs("epoch_number = {}, epoch_block_hash = {}".format(epoch_number, epoch_block_hash), self.nodes, DEBUG_MODE)

        amount_cert_2 = []

        bal_before_cert_2 = self.nodes[1].getbalance("", 0)
        mark_logs("Node1 balance before epoch 1 certificate is received: {}".format(bal_before_cert_2), self.nodes, DEBUG_MODE)        

        mark_logs("Generate new certificate for epoch {}. No bwt and no fee are included".format(epoch_number), self.nodes, DEBUG_MODE)

        # Create new proof for WCert
        quality = 1
        proof = mcTest.create_test_proof(
            "sc1", epoch_number, epoch_block_hash, prev_epoch_block_hash,
            quality, constant, [], [])

        nullFee = Decimal("0.0")
        try:
            cert_epoch_1 = self.nodes[0].send_certificate(scid, epoch_number, quality, epoch_block_hash, proof, amount_cert_2, nullFee)
            assert(len(cert_epoch_1) > 0)
            mark_logs("Certificate is {}".format(cert_epoch_1), self.nodes, DEBUG_MODE)
            self.sync_all()
        except JSONRPCException, e:
            errorString = e.error['message']
            mark_logs("Send certificate failed with reason {}".format(errorString), self.nodes, DEBUG_MODE)
            assert(False)

        # if txindex has not been specified when starting zend, this certificate can be retrieved only while is
        # in mempool, since it has no coins to be searched in the coins db
        mark_logs("Check the certificate for this scid has no vin and no vouts", self.nodes, DEBUG_MODE)
        try:
            ret = self.nodes[0].getrawcertificate(cert_epoch_1, 1)
            assert_equal(ret['cert']['scid'], scid)
            assert_equal(len(ret['vin']), 0)
            assert_equal(len(ret['vout']), 0)
        except JSONRPCException, e:
            errorString = e.error['message']
            mark_logs("can not get raw info for cert {} error: {}".format(cert_epoch_1, errorString), self.nodes, DEBUG_MODE)
    
        mark_logs("Confirm the certificate for epoch {} and move beyond safeguard".format(epoch_number), self.nodes, DEBUG_MODE)
        self.nodes[0].generate(1)
        h = self.nodes[0].getblockcount()
        self.nodes[0].generate(2)
        self.sync_all()

        bal_after_cert_2 = self.nodes[1].getbalance("", 0)
        mark_logs("Node1 balance after epoch 1 certificate is received and safeguard passed: {}".format(bal_after_cert_2), self.nodes, DEBUG_MODE)        

        mark_logs("Checking that certificate received from previous epoch is spendable,".format(epoch_number), self.nodes, DEBUG_MODE)
        retrieved_cert = self.nodes[1].gettransaction(cert_epoch_0)
        assert_equal(retrieved_cert['amount'], amount_cert_1[0]["amount"])  # Certificate amount has matured
        assert_equal(retrieved_cert['details'][0]['category'], "receive")
        assert_equal(retrieved_cert['details'][0]['amount'], amount_cert_1[0]["amount"])  # In cert details you can see the actual amount transferred

        assert_equal(self.nodes[1].getwalletinfo()['immature_balance'], Decimal(0))
        utxos_Node1 = self.nodes[1].listunspent()
        cert_epoch_0_availalble = False
        for utxo in utxos_Node1:
            if ("certified" in utxo.keys()):
                cert_epoch_0_availalble = True
                assert_true(utxo["txid"] == cert_epoch_0)
        assert_true(cert_epoch_0_availalble)

        mark_logs("Checking Node1 balance is duly updated,".format(epoch_number), self.nodes, DEBUG_MODE)
        assert_equal(bal_after_cert_2, bal_before_cert_2 + amount_cert_1[0]["amount"])

        Node2_bal_before_cert_expenditure = self.nodes[2].getbalance("", 0)
        mark_logs("Checking that Node1 can spend coins received from bwd transfer in previous epoch", self.nodes, DEBUG_MODE)
        mark_logs("Node 1 sends {} coins to node2...".format(amount_cert_1[0]["amount"] / 2), self.nodes, DEBUG_MODE)
        try:
            tx = self.nodes[1].sendtoaddress(self.nodes[2].getnewaddress(), amount_cert_1[0]["amount"] / 2)
            assert(len(tx) > 0)
        except JSONRPCException, e:
            errorString = e.error['message']
            mark_logs("tx spending certificate failed with reason {}".format(errorString), self.nodes, DEBUG_MODE)
            assert(False)

        vin = self.nodes[1].getrawtransaction(tx, 1)['vin']
        assert_equal(vin[0]['txid'], cert_epoch_0)

        mark_logs("Node0 confims spending of bwd transfer founds generating 1 block", self.nodes, DEBUG_MODE)
        self.sync_all()
        self.nodes[0].generate(1)
        self.sync_all()

        Node2_bal_after_cert_expenditure = self.nodes[2].getbalance("", 0)

        mark_logs("Verify balances following Node1 spending bwd transfer to Node2.", self.nodes, DEBUG_MODE)
        assert_equal(Node2_bal_before_cert_expenditure + amount_cert_1[0]["amount"] / 2, Node2_bal_after_cert_expenditure)

        mark_logs("Node 0 tries to send a certificate for old epoch {}...".format(epoch_number_0), self.nodes, DEBUG_MODE)
        amounts = []
        try:
            self.nodes[0].send_certificate(scid, epoch_number_0, 0, epoch_block_hash_0, proof, amounts, CERT_FEE)
            assert(False)
        except JSONRPCException, e:
            errorString = e.error['message']
            mark_logs(errorString, self.nodes, DEBUG_MODE)
        assert_equal("invalid epoch data" in errorString, True)




if __name__ == '__main__':
    ws_messages().main()