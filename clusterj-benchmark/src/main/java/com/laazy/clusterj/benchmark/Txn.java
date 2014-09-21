package com.laazy.clusterj.benchmark;

import com.mysql.clusterj.annotation.Column;
import com.mysql.clusterj.annotation.PersistenceCapable;
import com.mysql.clusterj.annotation.PrimaryKey;

@PersistenceCapable(table="transactions")
public interface Txn {

    @PrimaryKey
    @Column(name="account_id")
    int getAccountID();
    void setAccountID(int accountID);

    @Column(name="txn_id")
    int getTransactionID();
    void setTransactionID(int transactionID);

    int getTimestamp();
    void setTimestamp(int timestamp);

    boolean getPosted();
    void setPosted(boolean posted);

    float getAmount();
    void setAmount(float amount);
}
