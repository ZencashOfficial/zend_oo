#include "sc/sidechaintypes.h"
#include "util.h"
#include <consensus/consensus.h>

void CZendooCctpLibraryChecker::CheckTypeSizes()
{
    if (Sidechain::SC_FE_SIZE_IN_BYTES != zendoo_get_field_size_in_bytes())
    {
        LogPrintf("%s():%d - ERROR: unexpected CCTP field element size: %d (rust lib returns %d)\n", 
            __func__, __LINE__, Sidechain::SC_FE_SIZE_IN_BYTES, zendoo_get_field_size_in_bytes());
        assert(!"ERROR: field element size mismatch between rust CCTP lib and c header!");
    }
    if (Sidechain::MAX_SC_CUSTOM_DATA_LEN != zendoo_get_sc_custom_data_size_in_bytes())
    {
        LogPrintf("%s():%d - ERROR: unexpected CCTP custom data size: %d (rust lib returns %d)\n", 
            __func__, __LINE__, Sidechain::MAX_SC_CUSTOM_DATA_LEN, zendoo_get_sc_custom_data_size_in_bytes());
        assert(!"ERROR: custom data size mismatch between rust CCTP lib and c header!");
    }
}

const std::vector<unsigned char>&  CZendooCctpObject::GetByteArray() const
{
    return byteVector;
}

const unsigned char* const CZendooCctpObject::GetDataBuffer() const
{
    if (GetByteArray().empty())
        return nullptr;

    return &GetByteArray()[0];
}

int CZendooCctpObject::GetDataSize() const
{
    return GetByteArray().size();
}

void CZendooCctpObject::SetNull() { byteVector.resize(0); }
bool CZendooCctpObject::IsNull() const { return byteVector.empty();}

std::string CZendooCctpObject::GetHexRepr() const
{
    std::string res; //ADAPTED FROM UTILSTRENCONDING.CPP HEXSTR
    static const char hexmap[16] = { '0', '1', '2', '3', '4', '5', '6', '7',
                                     '8', '9', 'a', 'b', 'c', 'd', 'e', 'f' };
    res.reserve(this->byteVector.size()*2);
    for(const auto& byte: this->byteVector)
    {
        res.push_back(hexmap[byte>>4]);
        res.push_back(hexmap[byte&15]);
    }

    return res;
}

///////////////////////////////// Field types //////////////////////////////////
#ifdef BITCOIN_TX
CFieldElement::CFieldElement(const std::vector<unsigned char>& byteArrayIn) {};
void CFieldElement::SetByteArray(const std::vector<unsigned char>& byteArrayIn) {};
CFieldElement::CFieldElement(const uint256& value) {};
CFieldElement::CFieldElement(const wrappedFieldPtr& wrappedField) {};
uint256 CFieldElement::GetLegacyHash() const { return uint256(); };
wrappedFieldPtr CFieldElement::GetFieldElement() const {return nullptr;};
bool CFieldElement::IsValid() const {return false;};
CFieldElement CFieldElement::ComputeHash(const CFieldElement& lhs, const CFieldElement& rhs) { return CFieldElement{}; }
#else
CFieldElement::CFieldElement(const std::vector<unsigned char>& byteArrayIn): CZendooCctpObject(byteArrayIn)
{
    assert(byteArrayIn.size() == this->ByteSize());
}
void CFieldElement::SetByteArray(const std::vector<unsigned char>& byteArrayIn)
{
    assert(byteArrayIn.size() == this->ByteSize());
    this->byteVector = byteArrayIn;
}

CFieldElement::CFieldElement(const uint256& value)
{
    this->byteVector.resize(CFieldElement::ByteSize(),0x0);
    std::copy(value.begin(), value.end(), this->byteVector.begin());
}

CFieldElement::CFieldElement(const wrappedFieldPtr& wrappedField)
{
    this->byteVector.resize(CFieldElement::ByteSize(),0x0);
    if (wrappedField.get() != 0)
    {
        CctpErrorCode code;
        zendoo_serialize_field(wrappedField.get(), &byteVector[0], &code);
        assert(code == CctpErrorCode::OK);
    }
}

wrappedFieldPtr CFieldElement::GetFieldElement() const
{
    if (byteVector.empty())
    {
        LogPrint("sc", "%s():%d - empty byteVector\n", __func__, __LINE__);
        return wrappedFieldPtr{nullptr};
    }

    if (byteVector.size() != ByteSize())
    {
        LogPrint("sc", "%s():%d - wrong fe size: byteVector[%d] != %d\n",
            __func__, __LINE__, byteVector.size(), ByteSize());
        return wrappedFieldPtr{nullptr};
    }

    CctpErrorCode code;
    wrappedFieldPtr res = {zendoo_deserialize_field(&this->byteVector[0], &code), theFieldPtrDeleter};
    if (code != CctpErrorCode::OK)
    {
        LogPrintf("%s():%d - could not deserialize: error code[0x%x]\n", __func__, __LINE__, code);
        return wrappedFieldPtr{nullptr};
    }

    return res;
}

uint256 CFieldElement::GetLegacyHash() const
{
    std::vector<unsigned char> tmp(this->byteVector.begin(), this->byteVector.begin()+32);
    return uint256(tmp);
}

bool CFieldElement::IsValid() const
{
    if(this->GetFieldElement() == nullptr)
        return false;

    return true;
}

CFieldElement CFieldElement::ComputeHash(const CFieldElement& lhs, const CFieldElement& rhs)
{
    if(!lhs.IsValid() || !rhs.IsValid())
        throw std::runtime_error("Could not compute poseidon hash on null field elements");

    CctpErrorCode code;
    ZendooPoseidonHashConstantLength digest{2, &code};
    if (code != CctpErrorCode::OK)
    {
        LogPrintf("%s():%d - ERROR: code[0x%x]\n", __func__, __LINE__, code);
        throw std::runtime_error("Could not compute poseidon hash on null field elements");
    }

    wrappedFieldPtr sptr1 = lhs.GetFieldElement();
    digest.update(sptr1.get(), &code);
    if (code != CctpErrorCode::OK)
    {
        LogPrintf("%s():%d - ERROR: code[0x%x]\n", __func__, __LINE__, code);
        throw std::runtime_error("Could not compute poseidon hash on null field elements");
    }

    wrappedFieldPtr sptr2 = rhs.GetFieldElement();
    digest.update(sptr2.get(), &code);
    if (code != CctpErrorCode::OK)
    {
        LogPrintf("%s():%d - ERROR: code[0x%x]\n", __func__, __LINE__, code);
        throw std::runtime_error("Could not compute poseidon hash on null field elements");
    }

    wrappedFieldPtr res = {digest.finalize(&code), theFieldPtrDeleter};
    if (code != CctpErrorCode::OK)
    {
        LogPrintf("%s():%d - ERROR: code[0x%x]\n", __func__, __LINE__, code);
        throw std::runtime_error("Could not compute poseidon hash on null field elements");
    }

    return CFieldElement(res);
}

const CFieldElement& CFieldElement::GetPhantomHash()
{
    // TODO call an utility method to retrieve from zendoo_mc_cryptolib a constant phantom hash
    // field element and use it everywhere it is needed a constant value whose preimage has to
    // be unknown
    static CFieldElement ret{std::vector<unsigned char>(CFieldElement::ByteSize(), 0x00)};
    return ret;
}
#endif
///////////////////////////// End of CFieldElement /////////////////////////////

/////////////////////////////////// CScProof ///////////////////////////////////
CScProof::CScProof(const std::vector<unsigned char>& byteArrayIn): CZendooCctpObject(byteArrayIn)
{
    assert(byteArrayIn.size() <= this->MaxByteSize());
}

void CScProof::SetByteArray(const std::vector<unsigned char>& byteArrayIn)
{
    assert(byteArrayIn.size() <= this->MaxByteSize());
    this->byteVector = byteArrayIn;
}

wrappedScProofPtr CScProof::GetProofPtr() const
{
    if (this->byteVector.empty())
        return wrappedScProofPtr{nullptr};

    CctpErrorCode code;
    BufferWithSize result{(unsigned char*)&byteVector[0], byteVector.size()}; 
    wrappedScProofPtr res = {zendoo_deserialize_sc_proof(&result, true, &code), theProofPtrDeleter};
    if (code != CctpErrorCode::OK)
    {
        LogPrintf("%s():%d - ERROR: code[0x%x]\n", __func__, __LINE__, code);
        return wrappedScProofPtr{nullptr};
    }
    return res;
}

bool CScProof::IsValid() const
{
    if (this->GetProofPtr() == nullptr)
        return false;

    return true;
}

Sidechain::ProvingSystemType CScProof::getProvingSystemType() const
{
    CctpErrorCode code;
    auto sptr = GetProofPtr();
    ProvingSystem psType = zendoo_get_sc_proof_proving_system_type(sptr.get(), &code);
    if (code != CctpErrorCode::OK)
    {
        LogPrintf("%s():%d - ERROR: code[0x%x]\n", __func__, __LINE__, code);
        return Sidechain::ProvingSystemType::Undefined;
    }
    return static_cast<Sidechain::ProvingSystemType>(psType);
}

//////////////////////////////// End of CScProof ///////////////////////////////

//////////////////////////////////// CScVKey ///////////////////////////////////
CScVKey::CScVKey(const std::vector<unsigned char>& byteArrayIn)
    :CZendooCctpObject(byteArrayIn)
{
    assert(byteArrayIn.size() <= this->MaxByteSize());
}

CScVKey::CScVKey(): CZendooCctpObject()
{
}

void CScVKey::SetByteArray(const std::vector<unsigned char>& byteArrayIn)
{
    assert(byteArrayIn.size() <= this->MaxByteSize());
    this->byteVector = byteArrayIn;
}

wrappedScVkeyPtr CScVKey::GetVKeyPtr() const
{
    if (this->byteVector.empty())
        return wrappedScVkeyPtr{nullptr};

    CctpErrorCode code;
    BufferWithSize result{(unsigned char*)&byteVector[0], byteVector.size()}; 
    wrappedScVkeyPtr res = {zendoo_deserialize_sc_vk(&result, true, &code), theVkPtrDeleter};
    if (code != CctpErrorCode::OK)
    {
        LogPrintf("%s():%d - ERROR: code[0x%x]\n", __func__, __LINE__, code);
        return wrappedScVkeyPtr{nullptr};
    }
    return res;
}

bool CScVKey::IsValid() const
{
    if (this->GetVKeyPtr() == nullptr)
        return false;

    return true;
}

Sidechain::ProvingSystemType CScVKey::getProvingSystemType() const
{
    CctpErrorCode code;
    wrappedScVkeyPtr sptr = GetVKeyPtr();
    ProvingSystem psType = zendoo_get_sc_vk_proving_system_type(sptr.get(), &code);
    if (code != CctpErrorCode::OK)
    {
        LogPrintf("%s():%d - ERROR: code[0x%x]\n", __func__, __LINE__, code);
        return Sidechain::ProvingSystemType::Undefined;
    }
    return static_cast<Sidechain::ProvingSystemType>(psType);
}

//////////////////////////////// End of CScVKey ////////////////////////////////

////////////////////////////// Custom Config types //////////////////////////////
bool FieldElementCertificateFieldConfig::IsValid() const
{
    if(nBits > 0 && nBits <= CFieldElement::ByteSize()*8)
        return true;
    else
        return false;
}

FieldElementCertificateFieldConfig::FieldElementCertificateFieldConfig(uint8_t nBitsIn):
    CustomCertificateFieldConfig(), nBits(nBitsIn) {}

uint8_t FieldElementCertificateFieldConfig::getBitSize() const
{
    return nBits;
}

//----------------------------------------------------------------------------------
bool BitVectorCertificateFieldConfig::IsValid() const
{
    bool isBitVectorSizeValid = (bitVectorSizeBits > 0) && (bitVectorSizeBits <= MAX_BIT_VECTOR_SIZE_BITS);
    if(!isBitVectorSizeValid)
        return false;

    if ((bitVectorSizeBits % 254 != 0) || (bitVectorSizeBits % 8 != 0))
        return false;

    int32_t merkleTreeLeaves = bitVectorSizeBits / 254;

    // Check that the number of leaves of the Merkle tree built on top of the BitVector is a power of two
    if (merkleTreeLeaves & (merkleTreeLeaves - 1))
        return false;

    bool isMaxCompressedSizeValid = (maxCompressedSizeBytes > 0) && (maxCompressedSizeBytes <= MAX_COMPRESSED_SIZE_BYTES);
    if(!isMaxCompressedSizeValid)
        return false;

    return true;
}

BitVectorCertificateFieldConfig::BitVectorCertificateFieldConfig(int32_t bitVectorSizeBitsIn, int32_t maxCompressedSizeBytesIn):
    CustomCertificateFieldConfig(),
    bitVectorSizeBits(bitVectorSizeBitsIn),
    maxCompressedSizeBytes(maxCompressedSizeBytesIn) {
    BOOST_STATIC_ASSERT(MAX_COMPRESSED_SIZE_BYTES <= MAX_CERT_SIZE); // sanity
}


////////////////////////////// Custom Field types //////////////////////////////
//----------------------------------------------------------------------------------------
FieldElementCertificateField::FieldElementCertificateField(const std::vector<unsigned char>& rawBytes)
    :CustomCertificateField(rawBytes), pReferenceCfg{nullptr} {}

FieldElementCertificateField::FieldElementCertificateField(const FieldElementCertificateField& rhs)
    :CustomCertificateField{}, pReferenceCfg{nullptr}
{
    *this = rhs;
}

FieldElementCertificateField& FieldElementCertificateField::operator=(const FieldElementCertificateField& rhs)
{
    state = rhs.state;
    fieldElement =  rhs.fieldElement;
    *const_cast<std::vector<unsigned char>*>(&vRawData) = rhs.vRawData;

    if (rhs.pReferenceCfg != nullptr)
        this->pReferenceCfg = new FieldElementCertificateFieldConfig(*rhs.pReferenceCfg);
    else
        this->pReferenceCfg = nullptr;
    return *this;
}

bool FieldElementCertificateField::IsValid(const FieldElementCertificateFieldConfig& cfg) const
{
    return !this->GetFieldElement(cfg).IsNull();
}

const CFieldElement& FieldElementCertificateField::GetFieldElement(const FieldElementCertificateFieldConfig& cfg) const
{
    if (state != VALIDATION_STATE::NOT_INITIALIZED)
    {
        assert(pReferenceCfg != nullptr);
        if (*pReferenceCfg == cfg)
        {
            return fieldElement;
        }

        // revalidated with new cfg
        delete this->pReferenceCfg;
        this->pReferenceCfg = nullptr;
    }

    state = VALIDATION_STATE::INVALID;
    this->fieldElement = CFieldElement{};
    this->pReferenceCfg = new FieldElementCertificateFieldConfig(cfg);

    int rem = 0;

    assert(cfg.getBitSize() <= CFieldElement::BitSize());

    int bytes = getBytesFromBits(cfg.getBitSize(), rem);

    if (vRawData.size() != bytes )
    {
        LogPrint("sc", "%s():%d - ERROR: wrong size: data[%d] != cfg[%d]\n",
            __func__, __LINE__, vRawData.size(), cfg.getBitSize());
        return fieldElement;
    }

    if (rem)
    {
        // check null bits in the last byte are as expected
        unsigned char lastByte = vRawData.back();
        int numbOfZeroBits = getTrailingZeroBitsInByte(lastByte);
        if (numbOfZeroBits < (CHAR_BIT - rem))
        {
            LogPrint("sc", "%s():%d - ERROR: wrong number of null bits in last byte[0x%x]: %d vs %d\n",
                __func__, __LINE__, lastByte, numbOfZeroBits, (CHAR_BIT - rem));
            return fieldElement;
        }
    }

    std::vector<unsigned char> extendedRawData = vRawData;
    extendedRawData.insert(extendedRawData.begin(), CFieldElement::ByteSize()-vRawData.size(), 0x0);

    fieldElement.SetByteArray(extendedRawData);
    if (fieldElement.IsValid())
    {
        state = VALIDATION_STATE::VALID;
    } else
    {
        fieldElement = CFieldElement{};
    }

    return fieldElement;
}

//----------------------------------------------------------------------------------
BitVectorCertificateField::BitVectorCertificateField(const std::vector<unsigned char>& rawBytes)
    :CustomCertificateField(rawBytes), pReferenceCfg{nullptr} {}

BitVectorCertificateField::BitVectorCertificateField(const BitVectorCertificateField& rhs)
    :CustomCertificateField(), pReferenceCfg{nullptr}
{
    *this = rhs;
}

BitVectorCertificateField& BitVectorCertificateField::operator=(const BitVectorCertificateField& rhs)
{
    state = rhs.state;
    fieldElement =  rhs.fieldElement;
    *const_cast<std::vector<unsigned char>*>(&vRawData) = rhs.vRawData;

    if (rhs.pReferenceCfg != nullptr)
        this->pReferenceCfg = new BitVectorCertificateFieldConfig(*rhs.pReferenceCfg);
    else
        this->pReferenceCfg = nullptr;
    return *this;
}

bool BitVectorCertificateField::IsValid(const BitVectorCertificateFieldConfig& cfg) const
{
    return !this->GetFieldElement(cfg).IsNull();
}

const CFieldElement& BitVectorCertificateField::GetFieldElement(const BitVectorCertificateFieldConfig& cfg) const
{
    if (state != VALIDATION_STATE::NOT_INITIALIZED)
    {
        assert(pReferenceCfg != nullptr);
        if (*pReferenceCfg == cfg)
        {
            return fieldElement;
        }

        // revalidated with new cfg
        delete this->pReferenceCfg;
        this->pReferenceCfg = nullptr;
    }

    state = VALIDATION_STATE::INVALID;
    this->pReferenceCfg = new BitVectorCertificateFieldConfig(cfg);

    if(vRawData.size() > cfg.getMaxCompressedSizeBytes()) {
        // this is invalid and fieldElement is Null 
        this->fieldElement = CFieldElement{};
        return fieldElement;
    }

    // Reconstruct MerkleTree from the compressed raw data of vRawField
    CctpErrorCode ret_code = CctpErrorCode::OK;
    BufferWithSize compressedData(&vRawData[0], vRawData.size());

    int rem = 0;
    int nBitVectorSizeBytes = getBytesFromBits(cfg.getBitVectorSizeBits(), rem);

    // the second parameter is the expected size of the uncompressed data. If this size is not matched the function returns
    // an error and a null filed element ptr
    field_t* fe = zendoo_merkle_root_from_compressed_bytes(&compressedData, nBitVectorSizeBytes, &ret_code);
    if (fe == nullptr)
    {
        LogPrint("sc", "%s():%d - ERROR(%d): could not get merkle root field el from compr bit vector of size %d, exp uncompr size %d\n",
            __func__, __LINE__, (int)ret_code, vRawData.size(), nBitVectorSizeBytes);
        this->fieldElement = CFieldElement{};
        return fieldElement;
    }
    this->fieldElement = CFieldElement{wrappedFieldPtr{fe, CFieldPtrDeleter{}}};
    state = VALIDATION_STATE::VALID;

    return fieldElement;
}

////////////////////////// End of Custom Field types ///////////////////////////
std::string Sidechain::ProvingSystemTypeHelp()
{
    std::string helpString;

    helpString += strprintf("%s, ", PROVING_SYS_TYPE_COBOUNDARY_MARLIN);
    helpString += strprintf("%s",   PROVING_SYS_TYPE_DARLIN);

    return helpString;
}

bool Sidechain::IsValidProvingSystemType(uint8_t val)
{
    return IsValidProvingSystemType(static_cast<ProvingSystemType>(val));
}

bool Sidechain::IsValidProvingSystemType(Sidechain::ProvingSystemType val)
{
    switch (val)
    {
        case ProvingSystemType::CoboundaryMarlin:
        case ProvingSystemType::Darlin:
            return true;
        default:
            return false;
    }
}

std::string Sidechain::ProvingSystemTypeToString(Sidechain::ProvingSystemType val)
{
    switch (val)
    {
        case ProvingSystemType::CoboundaryMarlin:
            return PROVING_SYS_TYPE_COBOUNDARY_MARLIN;
        case ProvingSystemType::Darlin:
            return PROVING_SYS_TYPE_DARLIN;
        default:
            return PROVING_SYS_TYPE_UNDEFINED;
    }
}

Sidechain::ProvingSystemType Sidechain::StringToProvingSystemType(const std::string& str)
{
    if (str == PROVING_SYS_TYPE_COBOUNDARY_MARLIN)
        return ProvingSystemType::CoboundaryMarlin;
    if (str == PROVING_SYS_TYPE_DARLIN)
        return ProvingSystemType::Darlin;
    return ProvingSystemType::Undefined;
}

bool Sidechain::IsUndefinedProvingSystemType(const std::string& str)
{
    // empty string or explicit undefined tag mean null semantic, others must be legal types 
    return (str.empty() || str == PROVING_SYS_TYPE_UNDEFINED);
}

void dumpBuffer(BufferWithSize* buf, const std::string& name)
{
    printf("==================================================================================\n");
    printf("### %s() - %s\n", __func__, name.c_str());
    printf("--------------------------------------------------------------------------------\n");
    if (buf == nullptr)
    {
        printf("----> Null Buffer\n");
        printf("==================================================================================\n");
        return;
    }

    const unsigned char* ptr = buf->data;
    size_t len = buf->len;

    printf("buffer address: %p\n", buf);
    printf("     data ptr : %p\n", ptr);
    printf("          len : %lu\n", len);
    printf("--------------------------------------------------------------------------------\n");

    if (ptr == nullptr)
    {
        printf("----> Null data ptr\n");
        printf("==================================================================================\n");
        return;
    }

    int row = 0;
    printf("contents:");
    for (int i = 0; i < len; i++)
    {
        if (i%32 == 0)
        {
            row++;
            printf("\n%5d)     ", row);
        }
        printf("%02x", *ptr++);
    }
    printf("\n\n");
}


void dumpBvCfg(BitVectorElementsConfig* buf, size_t len, const std::string& name)
{
    printf("==================================================================================\n");
    printf("### %s() - %s\n", __func__, name.c_str());
    printf("--------------------------------------------------------------------------------\n");
    if (buf == nullptr)
    {
        printf("----> Null Buffer Array\n");
        printf("==================================================================================\n");
        return;
    }


    printf("buffer arr address: %p\n", buf);
    printf("              len : %lu\n", len);
    printf("--------------------------------------------------------------------------------\n");

    BitVectorElementsConfig* ptr = buf;
    printf("contents:");
    for (int i = 0; i < len; i++)
    {
        printf("\n%3d)  %5d / %5d", i, ptr->bit_vector_size_bits, ptr->max_compressed_byte_size);
        ptr++;
    }
    printf("\n\n");
}

void dumpFe(field_t* fe, const std::string& name)
{
    printf("==================================================================================\n");
    printf("### %s() - %s\n", __func__, name.c_str());
    printf("--------------------------------------------------------------------------------\n");
    if (fe == nullptr)
    {
        printf("----> Null Fe\n");
        printf("==================================================================================\n");
        return;
    }

    unsigned char* ptr = (unsigned char*)fe;
    printf("     contents: [");
    for (int i = 0; i < CFieldElement::ByteSize(); i++)
    {
        printf("%02x", *ptr);
        ptr++;
    }
    printf("]\n");

    CctpErrorCode code;
    unsigned char serialized_buffer[CFieldElement::ByteSize()] = {};
    zendoo_serialize_field(fe, serialized_buffer, &code);
    if (code != CctpErrorCode::OK)
    {
        printf("----> Could not serialize Fe\n");
        printf("==================================================================================\n");
        return;
    }

    ptr = serialized_buffer;
    printf("serialized fe: [");
    for (int i = 0; i < CFieldElement::ByteSize(); i++)
    {
        printf("%02x", *ptr);
        ptr++;
    }
    printf("]\n\n");
}

void dumpFeArr(field_t** feArr, size_t len, const std::string& name)
#ifndef BITCOIN_TX
{
    printf("==================================================================================\n");
    printf("### %s() - %s\n", __func__, name.c_str());
    printf("--------------------------------------------------------------------------------\n");
    if (feArr == nullptr)
    {
        printf("----> Null Fe\n");
        printf("==================================================================================\n");
        return;
    }

    static const size_t BUF_SIZE = 32;
    for (size_t i = 0; i < len; i++)
    {
        char buf[BUF_SIZE] = {};
        snprintf(buf, BUF_SIZE, "fe %2lu)", i);
        field_t* fe = feArr[i];
        dumpFe(fe, std::string(buf));
    }

}
#else
{}
#endif
