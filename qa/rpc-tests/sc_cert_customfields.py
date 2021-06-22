#!/usr/bin/env python2
# Copyright (c) 2014 The Bitcoin Core developers
# Copyright (c) 2018 The Zencash developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
from test_framework.test_framework import BitcoinTestFramework
from test_framework.authproxy import JSONRPCException
from test_framework.util import assert_true, assert_equal, initialize_chain_clean, \
    start_nodes, stop_nodes, wait_bitcoinds, sync_blocks, sync_mempools, connect_nodes_bi, mark_logs, \
    dump_sc_info, dump_sc_info_record, get_epoch_data, get_spendable, swap_bytes
from test_framework.mc_test.mc_test import CertTestUtils, generate_random_field_element_hex
import os
import pprint
from decimal import Decimal
import json

NUMB_OF_NODES = 2
DEBUG_MODE = 1
EPOCH_LENGTH = 5
FT_SC_FEE = Decimal('0')
MBTR_SC_FEE = Decimal('0')
CERT_FEE = Decimal("0.000123")

BIT_VECTOR_BUF = "021f8b08000000000002ff017f0080ff44c7e21ba1c7c0a29de006cb8074e2ba39f15abfef2525a4cbb3f235734410bda21cdab6624de769ceec818ac6c2d3a01e382e357dce1f6e9a0ff281f0fedae0efe274351db37599af457984dcf8e3ae4479e0561341adfff4746fbe274d90f6f76b8a2552a6ebb98aee918c7ceac058f4c1ae0131249546ef5e22f4187a07da02ca5b7f000000"
BIT_VECTOR_BUF_NOT_POW2 = "01425a68393141592653591dadce4d0000fe8180900000100008200030cc09aa69901b5403c5dc914e1424076b739340"
BIT_VECTOR_FE  = "8a7d5229f440d4700d8b0343de4e14400d1cb87428abf83bd67153bf58871721"

class sc_cert_customfields(BitcoinTestFramework):
    alert_filename = None

    def setup_chain(self, split=False):
        print("Initializing test directory " + self.options.tmpdir)
        initialize_chain_clean(self.options.tmpdir, NUMB_OF_NODES)
        self.alert_filename = os.path.join(self.options.tmpdir, "alert.txt")
        with open(self.alert_filename, 'w'):
            pass  # Just open then close to create zero-length file

    def setup_network(self, split=False):

        self.nodes = start_nodes(NUMB_OF_NODES, self.options.tmpdir,
                                 extra_args=[['-logtimemicros=1', '-debug=sc',
                                              '-debug=py', '-debug=mempool', '-debug=net', '-debug=cert',
                                              '-debug=bench']] * NUMB_OF_NODES)

        connect_nodes_bi(self.nodes, 0, 1)
        self.is_network_split = split
        self.sync_all()

    def run_test(self):
        '''
        Create a few SCs specifying related configurations for the custom fields that a cert must set; during
        this phase, different versions of cmd for SC creation are tested.
        Send some certificate with custom fields configured accordingly to the SC they refer.
        Along the test execution, some negative test is also performed.
        JSON representation of scinfo as well as tx/cert are checked for expected contents too.
        '''

        # network topology: (0)--(1)

        mark_logs("Node 1 generates 2 block",self.nodes,DEBUG_MODE)
        self.nodes[1].generate(2)
        self.sync_all()

        mark_logs("Node 0 generates 220 block",self.nodes,DEBUG_MODE)
        self.nodes[0].generate(220)
        self.sync_all()

        #generate wCertVk and constant
        mcTest = CertTestUtils(self.options.tmpdir, self.options.srcdir)
        vk = mcTest.generate_params('sc1')
        constant1 = generate_random_field_element_hex()

        amount = 1.0
        fee = 0.000025

        #-------------------------------------------------------
        bad_obj = {"a":1, "b":2}
        cmdInput = {
            'withdrawalEpochLength': EPOCH_LENGTH, 'vFieldElementCertificateFieldConfig': bad_obj,
            'toaddress': "abcd", 'amount': amount, 'fee': fee, 'wCertVk': vk}

        mark_logs("\nNode 1 create SC with wrong vFieldElementCertificateFieldConfig obj in input (expecting failure...)", self.nodes, DEBUG_MODE)
        try:
            self.nodes[1].create_sidechain(cmdInput)
            assert_true(False)
        except JSONRPCException, e:
            errorString = e.error['message']
            mark_logs(errorString,self.nodes,DEBUG_MODE)
            assert_true("not an array" in errorString)

        #-------------------------------------------------------
        bad_array = ["hello", "world"]
        cmdInput = {'vBitVectorCertificateFieldConfig': bad_array, 'toaddress': "abcd", 'amount': amount, 'fee': fee, 'wCertVk': vk}

        mark_logs("\nNode 1 create SC with wrong vBitVectorCertificateFieldConfig array in input (expecting failure...)", self.nodes, DEBUG_MODE)
        try:
            self.nodes[1].create_sidechain(cmdInput)
            assert_true(False)
        except JSONRPCException, e:
            errorString = e.error['message']
            mark_logs(errorString,self.nodes,DEBUG_MODE)
            assert_true("Invalid vBitVectorCertificateFieldConfig" in errorString)

        #-------------------------------------------------------
        too_large_array_values = [[1000761, 31]] # [1000192, 1000192/8] at most
        cmdInput = {'vBitVectorCertificateFieldConfig': too_large_array_values, 'toaddress': "abcd", 'amount': amount, 'fee': fee, 'wCertVk': vk}

        mark_logs("\nNode 1 create SC with a vBitVectorCertificateFieldConfig array with too large integers (expecting failure...)", self.nodes, DEBUG_MODE)
        try:
            self.nodes[1].create_sidechain(cmdInput)
            assert_true(False)
        except JSONRPCException, e:
            errorString = e.error['message']
            mark_logs(errorString,self.nodes,DEBUG_MODE)
            assert_true("invalid-custom-config" in errorString)

        #-------------------------------------------------------
        zero_values_array = [0, 0]
        cmdInput = {'vFieldElementCertificateFieldConfig': zero_values_array, 'toaddress': "abcd", 'amount': amount, 'fee': fee, 'wCertVk': vk}

        mark_logs("\nNode 1 create SC with a vFieldElementCertificateFieldConfig array with zeroes (expecting failure...)", self.nodes, DEBUG_MODE)
        try:
            self.nodes[1].create_sidechain(cmdInput)
            assert_true(False)
        except JSONRPCException, e:
            errorString = e.error['message']
            mark_logs(errorString,self.nodes,DEBUG_MODE)
            assert_true("Invalid parameter, expected positive integer in the range [1,..,255]" in errorString)

        #-------------------------------------------------------
        not_power_of_two_array = [[1039368, 151]]
        cmdInput = {'vBitVectorCertificateFieldConfig': not_power_of_two_array, 'toaddress': "abcd", 'amount': amount, 'fee': fee, 'wCertVk': vk}

        mark_logs("\nNode 1 create SC with a BitVector made of a number of FE leaves that is not a power of 2 (expecting failure...)", self.nodes, DEBUG_MODE)
        try:
            self.nodes[1].create_sidechain(cmdInput)
            assert_true(False)
        except JSONRPCException, e:
            errorString = e.error['message']
            mark_logs(errorString,self.nodes,DEBUG_MODE)
            assert_true("sidechain-sc-creation-invalid-custom-config" in errorString)

        #-------------------------------------------------------
        fee = 0.000025
        feCfg = []
        cmtCfg = []

        # all certs must have custom FieldElements with exactly those values as size in bits 
        feCfg.append([31, 48, 16])

        # one custom bv element with:
        # - as many bits in the uncompressed form (must be divisible by 254 and 8)
        # - up to 151 bytes in the compressed form
        cmtCfg.append([[254*4, 151]])

        cmdInput = {
            'withdrawalEpochLength': EPOCH_LENGTH, 'amount': amount, 'fee': fee,
            'constant':constant1 , 'wCertVk': vk, 'toaddress':"cdcd",
            'vFieldElementCertificateFieldConfig':feCfg[0], 'vBitVectorCertificateFieldConfig':cmtCfg[0] }

        mark_logs("\nNode 1 create SC1 with valid vFieldElementCertificateFieldConfig / vBitVectorCertificateFieldConfig pair", self.nodes,DEBUG_MODE)
        try:
            res = self.nodes[1].create_sidechain(cmdInput)
            tx =   res['txid']
            scid1 = res['scid']
        except JSONRPCException, e:
            errorString = e.error['message']
            mark_logs(errorString,self.nodes,DEBUG_MODE)
            assert_true(False)

        self.sync_all()

        mark_logs("Verify vFieldElementCertificateFieldConfig / vBitVectorCertificateFieldConfig are correctly set in creation tx", self.nodes,DEBUG_MODE)
        decoded_tx = self.nodes[1].getrawtransaction(tx, 1)
        dec_sc_id = decoded_tx['vsc_ccout'][0]['scid']
        assert_equal(scid1, dec_sc_id)

        feCfgStr  = decoded_tx['vsc_ccout'][0]['vFieldElementCertificateFieldConfig']
        cmtCfgStr = decoded_tx['vsc_ccout'][0]['vBitVectorCertificateFieldConfig']
        assert_equal(feCfgStr, feCfg[0])
        assert_equal(cmtCfgStr, cmtCfg[0])

        # test two more SC creations with different versions of the cmd
        #-------------------------------------------------------
        vk = mcTest.generate_params("sc2")
        constant2 = generate_random_field_element_hex()
        customData = "c0ffee"
        cswVk  = ""
        feCfg.append([16])
        cmtCfg.append([])

        mark_logs("\nNode 1 create SC2 with valid vFieldElementCertificateFieldConfig / vBitVectorCertificateFieldConfig pair", self.nodes,DEBUG_MODE)
        try:
            ret = self.nodes[1].sc_create(EPOCH_LENGTH, "dada", amount, vk, customData, constant2, cswVk, feCfg[1], cmtCfg[1])
        except JSONRPCException, e:
            errorString = e.error['message']
            mark_logs(errorString,self.nodes,DEBUG_MODE)
            assert_true(False)
        self.sync_all()
 
        mark_logs("Verify vFieldElementCertificateFieldConfig / vBitVectorCertificateFieldConfig are correctly set in creation tx", self.nodes,DEBUG_MODE)
        creating_tx = ret['txid']
        scid2 = ret['scid']

        decoded_tx = self.nodes[1].getrawtransaction(creating_tx, 1)
        dec_sc_id = decoded_tx['vsc_ccout'][0]['scid']
        assert_equal(scid2, dec_sc_id)

        feCfgStr  = decoded_tx['vsc_ccout'][0]['vFieldElementCertificateFieldConfig']
        cmtCfgStr = decoded_tx['vsc_ccout'][0]['vBitVectorCertificateFieldConfig']
        assert_equal(feCfgStr, feCfg[1])
        assert_equal(cmtCfgStr, cmtCfg[1])

        #-------------------------------------------------------
        vk = mcTest.generate_params("sc3")
        constant3 = generate_random_field_element_hex()
        customData = "c0ffee"
        feCfg.append([])
        cmtCfg.append([[254*8*4, 1967]])

        sc_cr = [{
            "epoch_length": EPOCH_LENGTH, "amount":amount, "address":"ddaa", "wCertVk": vk, "constant": constant3,
            "vFieldElementCertificateFieldConfig":feCfg[2], "vBitVectorCertificateFieldConfig":cmtCfg[2] }]

        mark_logs("\nNode 0 create SC3 with valid vFieldElementCertificateFieldConfig / vBitVectorCertificateFieldConfig pair", self.nodes,DEBUG_MODE)
        try:
            rawtx=self.nodes[0].createrawtransaction([],{},[],sc_cr)
            funded_tx = self.nodes[0].fundrawtransaction(rawtx)
            sigRawtx = self.nodes[0].signrawtransaction(funded_tx['hex'])
            creating_tx = self.nodes[0].sendrawtransaction(sigRawtx['hex'])
        except JSONRPCException, e:
            errorString = e.error['message']
            mark_logs(errorString,self.nodes,DEBUG_MODE)
            assert_true(False)
        self.sync_all()
 
        mark_logs("Verify vFieldElementCertificateFieldConfig / vBitVectorCertificateFieldConfig are correctly set in creation tx", self.nodes,DEBUG_MODE)
        decoded_tx = self.nodes[0].getrawtransaction(creating_tx, 1)
        scid3 = decoded_tx['vsc_ccout'][0]['scid']

        feCfgStr  = decoded_tx['vsc_ccout'][0]['vFieldElementCertificateFieldConfig']
        cmtCfgStr = decoded_tx['vsc_ccout'][0]['vBitVectorCertificateFieldConfig']
        assert_equal(feCfgStr, feCfg[2])
        assert_equal(cmtCfgStr, cmtCfg[2])

        #-------------------------------------------------------
        mark_logs("\nNode 0 generates 1 block confirming SC creations", self.nodes, DEBUG_MODE)
        self.nodes[0].generate(1)
        self.sync_all()

        scids = [scid1, scid2, scid3]
        mark_logs("Verify vFieldElementCertificateFieldConfig / vBitVectorCertificateFieldConfig are correctly set in scinfo for all SCs", self.nodes,DEBUG_MODE)
        for i, val in enumerate(scids):
            feCfgStr  = self.nodes[0].getscinfo(val)['items'][0]['vFieldElementCertificateFieldConfig']
            cmtCfgStr = self.nodes[0].getscinfo(val)['items'][0]['vBitVectorCertificateFieldConfig']
            assert_equal(feCfgStr, feCfg[i])
            assert_equal(cmtCfgStr, cmtCfg[i])

        #-------------------------------------------------------
        # advance epoch
        certs = []
        mark_logs("\nNode 0 generates {} block".format(EPOCH_LENGTH-1), self.nodes, DEBUG_MODE)
        self.nodes[0].generate(EPOCH_LENGTH - 1)
        self.sync_all()

        epoch_number_1, epoch_cum_tree_hash_1 = get_epoch_data(scid1, self.nodes[0], EPOCH_LENGTH)
        mark_logs("epoch_number = {}, epoch_cum_tree_hash = {}".format(epoch_number_1, epoch_cum_tree_hash_1), self.nodes, DEBUG_MODE)

        #-------------------------------------------------------
        # do some negative test for having a raw cert rejected by mempool
        pkh_node1 = self.nodes[1].getnewaddress("", True)
        bwt_amount = Decimal("0.1")

        # get a UTXO
        utx, change = get_spendable(self.nodes[0], CERT_FEE)

        inputs  = [ {'txid' : utx['txid'], 'vout' : utx['vout']}]
        outputs = { self.nodes[0].getnewaddress() : change }
        bwt_outs = {pkh_node1: bwt_amount}

        # cfgs for SC2: [16], []
        mark_logs("\nCreate raw cert with wrong field element for the referred SC2 (expecting failure)...", self.nodes, DEBUG_MODE)

        # custom fields are not consistent with cfg: should fail
        vCfe = ["abcd1234", "ccccddddeeee", "aaee"]
        vCmt = ["1111", "0660101a"]

        # this proof would be invalid but we expect an early failure
        scProof2 = mcTest.create_test_proof(
            'sc2', epoch_number_1, 10, MBTR_SC_FEE, FT_SC_FEE, constant2, epoch_cum_tree_hash_1, [pkh_node1], [bwt_amount])

        params = {
            'scid': scid2,
            'quality': 10,
            'scProof': scProof2,
            'endEpochCumScTxCommTreeRoot': epoch_cum_tree_hash_1,
            'withdrawalEpochNumber': epoch_number_1,
            'vFieldElementCertificateField': vCfe,
            'vBitVectorCertificateField':vCmt
        }
        try:
            rawcert    = self.nodes[0].createrawcertificate(inputs, outputs, bwt_outs, params)
            signed_cert = self.nodes[0].signrawcertificate(rawcert)
            self.nodes[0].sendrawcertificate(signed_cert['hex'])
            assert (False)
        except JSONRPCException, e:
            errorString = e.error['message']
            mark_logs("Send certificate failed with reason {}".format(errorString), self.nodes, DEBUG_MODE)
            assert_true("bad-sc-cert-not-applicable" in errorString)

        #-------------------------------------------------------
        mark_logs("\nCreate raw cert with good custom field elements for SC2...", self.nodes, DEBUG_MODE)
        # cfgs for SC2: [16], []
        # we must be careful with ending bits for having valid fe.
        vCfe = ["0100"]
        vCmt = []

        # serialized fe for the proof has 32 byte size
        fe1 = "000000000000000000000000000000000000000000000000000000000000" + "0100"

        scProof3 = mcTest.create_test_proof(
            'sc2', epoch_number_1, 10, MBTR_SC_FEE, FT_SC_FEE, constant2, epoch_cum_tree_hash_1, [pkh_node1], [bwt_amount],
            [fe1])

        print "cum =", epoch_cum_tree_hash_1
        params = {
            'scid': scid2,
            'quality': 10,
            'endEpochCumScTxCommTreeRoot': epoch_cum_tree_hash_1,
            'scProof': scProof3,
            'withdrawalEpochNumber': epoch_number_1,
            'vFieldElementCertificateField': vCfe,
            'vBitVectorCertificateField':vCmt
        }

        try:
            rawcert = self.nodes[0].createrawcertificate(inputs, outputs, bwt_outs, params)
            signed_cert = self.nodes[0].signrawcertificate(rawcert)
            cert = self.nodes[0].sendrawcertificate(signed_cert['hex'])
        except JSONRPCException, e:
            errorString = e.error['message']
            mark_logs("Send certificate failed with reason {}".format(errorString), self.nodes, DEBUG_MODE)
            assert (False)

        self.sync_all()
        mark_logs("Check cert is in mempools", self.nodes, DEBUG_MODE)
        assert_equal(True, cert in self.nodes[0].getrawmempool())
        certs.append(cert)

        #-------------------------------------------------------
        # get another UTXO
        utx, change = get_spendable(self.nodes[0], CERT_FEE)
        inputs  = [ {'txid' : utx['txid'], 'vout' : utx['vout']}]
        outputs = { self.nodes[0].getnewaddress() : change }

        # cfgs for SC1: [31, 48, 16], [[254*4, 151]]
        mark_logs("Create raw cert with bad custom field elements for SC1... (expecting failure)", self.nodes, DEBUG_MODE)

        # In 0xcd (last byte of firts field) there are no trailing null bits, therefore it is not OK
        vCfe = ["abde12cd", "ccccbbbbeeee", "cbbd"]
        vCmt = ["1111"]

        # this proof would not be valid, but we expect an early failure
        scProof1 = mcTest.create_test_proof('sc1', epoch_number_1, 10, MBTR_SC_FEE, FT_SC_FEE, constant1, epoch_cum_tree_hash_1, [pkh_node1], [bwt_amount])

        params = {
            'scid': scid1,
            'quality': 10,
            'endEpochCumScTxCommTreeRoot': epoch_cum_tree_hash_1,
            'scProof': scProof1,
            'withdrawalEpochNumber': epoch_number_1,
            'vFieldElementCertificateField': vCfe,
            'vBitVectorCertificateField':vCmt
        }

        try:
            rawcert    = self.nodes[0].createrawcertificate(inputs, outputs, bwt_outs, params)
            signed_cert = self.nodes[0].signrawcertificate(rawcert)
            cert = self.nodes[0].sendrawcertificate(signed_cert['hex'])
            assert (False)
        except JSONRPCException, e:
            errorString = e.error['message']
            mark_logs("Send certificate failed with reason {}".format(errorString), self.nodes, DEBUG_MODE)
            assert_true("bad-sc-cert-not-applicable" in errorString)

        self.sync_all()
        mark_logs("\nCreate raw cert with good custom field elements for SC1...", self.nodes, DEBUG_MODE)

        # Any number ending with 0x00 is not over module for being a valid field element, therefore it is OK
        vCfe = ["ab000100", "ccccdddd0000", "0100"]
        # this is a compressed buffer which will yield a valid field element for the proof (see below)
        vCmt = [BIT_VECTOR_BUF]

        fe1 = "00000000000000000000000000000000000000000000000000000000" + "ab000100"
        fe2 = "0000000000000000000000000000000000000000000000000000" + "ccccdddd0000"
        fe3 = "000000000000000000000000000000000000000000000000000000000000" + "0100"
        fe4 = BIT_VECTOR_FE

        scProof3 = mcTest.create_test_proof(
            'sc1', epoch_number_1, 10, MBTR_SC_FEE, FT_SC_FEE, constant1, epoch_cum_tree_hash_1, [pkh_node1], [bwt_amount],
            [fe1, fe2, fe3, fe4])

        params = {
            'scid': scid1,
            'quality': 10,
            'endEpochCumScTxCommTreeRoot': epoch_cum_tree_hash_1,
            'scProof': scProof3,
            'withdrawalEpochNumber': epoch_number_1,
            'vFieldElementCertificateField': vCfe,
            'vBitVectorCertificateField':vCmt
        }

        try:
            rawcert = self.nodes[0].createrawcertificate(inputs, outputs, bwt_outs, params)
            signed_cert = self.nodes[0].signrawcertificate(rawcert)
            cert = self.nodes[0].sendrawcertificate(signed_cert['hex'])
        except JSONRPCException, e:
            errorString = e.error['message']
            mark_logs("Send certificate failed with reason {}".format(errorString), self.nodes, DEBUG_MODE)
            assert (False)
        self.sync_all()
        mark_logs("Check cert is in mempools", self.nodes, DEBUG_MODE)
        assert_equal(True, cert in self.nodes[0].getrawmempool())
        certs.append(cert)

        #-------------------------------------------------------
        # parse a good cert and check custom fields
        mark_logs("\nVerify vFieldElementCertificateField/ vBitVectorCertificateFieldare correctly set in cert", self.nodes,DEBUG_MODE)
        decoded = self.nodes[1].getrawcertificate(cert, 1)

        vCfeCert = decoded['cert']['vFieldElementCertificateField']
        assert_equal(vCfeCert, vCfe)
        for i, val in enumerate(vCfe):
            assert_equal(val, vCfeCert[i]) 

        vCmtCert = decoded['cert']['vBitVectorCertificateField']
        assert_equal(vCmtCert, vCmt)
        for i, val in enumerate(vCmt):
            assert_equal(val, vCmtCert[i]) 

        bestHash = self.nodes[0].generate(1)[-1]
        self.sync_all()

        # check that the cert for this epoch is correctly mined
        print("SC id = " + scid1)
        print("Block hash with cert = " + bestHash)
        print("Block with cert = " + self.nodes[0].getblock(bestHash, False))
        assert_true(cert in self.nodes[0].getblock(bestHash, True)['cert'])
        
        mark_logs("...stopping and restarting nodes", self.nodes, DEBUG_MODE)
        stop_nodes(self.nodes)
        wait_bitcoinds()
        self.setup_network(False)

        # check it again
        assert_true(cert in self.nodes[1].getblock(bestHash, True)['cert'])
        


if __name__ == '__main__':
    sc_cert_customfields().main()
