package com.laazy.clusterj.benchmark;

import com.mysql.clusterj.*;
import com.mysql.clusterj.query.PredicateOperand;
import com.mysql.clusterj.query.QueryDomainType;

import java.util.Arrays;
import java.util.List;
import java.util.Properties;

public class Main {
    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("usage: java -jar clusterj-benchmark.jar connectString (load|fetch)");
            System.exit(1);
        }

        String connectString = args[0];
        String operation = args[1];
        String[] remainingArgs = Arrays.copyOfRange(args, 2, args.length);
        run(connectString, operation, remainingArgs);
    }

    private static void run(String connectString, String operation, String[] args) throws Exception {
        switch (operation.toLowerCase()) {
            case "load":
                load(connectString, args);
                break;
            case "fetch":
                fetch(connectString, args);
                break;
            default:
                System.err.println("Unknown operation: " + operation);
                System.exit(1);
        }
        System.exit(0);
    }

    private static SessionFactory sessionFactory(String connectString) {
        Properties properties = new Properties();
        properties.setProperty("com.mysql.clusterj.connectstring", connectString);
        properties.setProperty("com.mysql.clusterj.database", "benchmarks");
        return ClusterJHelper.getSessionFactory(properties);
    }

    private static void load(String connectString, String[] args) throws Exception {
        if (args.length != 4) {
            System.err.println("usage: java -jar clusterj-benchmark.jar connectString load startingAccountID numAccounts numTxnPerAccount numThreads");
            System.exit(1);
        }

        int startingAccountID = Integer.parseInt(args[0]);
        int numAccounts = Integer.parseInt(args[1]);
        int numTxnPerAccount = Integer.parseInt(args[2]);
        int numThreads = Integer.parseInt(args[3]);

        SessionFactory sessionFactory = sessionFactory(connectString);
        try {
            load(sessionFactory, startingAccountID, numAccounts, numTxnPerAccount, numThreads);
        } finally {
            sessionFactory.close();
        }
    }

    private static void load(final SessionFactory sessionFactory, int startingAccountID, int numAccounts, final int numTxnPerAccount, int numThreads) throws Exception {
        Thread[] threads = new Thread[numThreads];
        for (int i = 0; i < threads.length; i++) {
            final int startAccountID = blockLow(i, numThreads, numAccounts) + startingAccountID;
            final int endAccountID = blockLow(i + 1, numThreads, numAccounts) + startingAccountID;
            threads[i] = new Thread(new Runnable() {
                @Override
                public void run() {
                    Session session = sessionFactory.getSession();
                    try {
                        for (int accountID = startAccountID; accountID < endAccountID; accountID++) {
                            createAccount(session, accountID, numTxnPerAccount);
                        }
                    } catch (Throwable t) {
                        t.printStackTrace();
                    } finally {
                        session.close();
                    }
                }
            });
            threads[i].start();
        }

        for (Thread thread : threads) {
            thread.join();
        }
    }

    private static void createAccount(Session session, int accountID, int numTxnPerAccount) {
        Transaction transaction = session.currentTransaction();
        transaction.begin();
        for (int transactionID = 0; transactionID < numTxnPerAccount; transactionID++) {
            Txn txn = session.newInstance(Txn.class);
            txn.setAccountID(accountID);
            txn.setTransactionID(transactionID);
            txn.setTimestamp((int) (System.currentTimeMillis() / 1000));
            txn.setPosted(Math.random() < 0.5);
            txn.setAmount((float) (200 * Math.random()));
            session.persist(txn);
        }
        transaction.commit();
    }

    private static void fetch(String connectionString, String[] args) {
        if (args.length != 1) {
            System.err.println("usage: java -jar clusterj-benchmark.jar connectString fetch accountID");
            System.exit(1);
        }

        int accountID = Integer.parseInt(args[0]);
        int numIterations = 10000;
        fetch(connectionString, accountID, numIterations);
    }

    private static void fetch(String connectString, int accountID, int numIterations) {
        SessionFactory sessionFactory = sessionFactory(connectString);
        try {
            fetch(sessionFactory, accountID, numIterations);
        } finally {
            sessionFactory.close();
        }
    }

    private static void fetch(SessionFactory sessionFactory, int accountID, int numIterations) {
        Session session = sessionFactory.getSession();
        try {
            fetch(session, accountID, numIterations);
        } finally {
            session.close();
        }
    }

    private static void fetch(Session session, int accountID, int numIterations) {
        session.setLockMode(LockMode.READ_COMMITTED);

        QueryDomainType<Txn> queryDefinition = session.getQueryBuilder().createQueryDefinition(Txn.class);
        PredicateOperand param = queryDefinition.param("accountID");
        queryDefinition.where(queryDefinition.get("accountID").equal(param));

        long totalTimeInNanos = 0;
        for (int i = 0; i < numIterations; i++) {
            long start = System.nanoTime();
            Query<Txn> query = session.createQuery(queryDefinition);
            query.setParameter("accountID", accountID);
            List<Txn> resultList = query.getResultList();
            long end = System.nanoTime();
            long durationInNanos = end - start;
            totalTimeInNanos += durationInNanos;
            System.out.printf("Fetch time: %.3fms%n", durationInNanos / 1e6);
        }
        System.out.printf("Avg query time: %.3fms%n", totalTimeInNanos / 1e6 / numIterations);
    }

    private static int blockLow(int id, int p, int n) {
        return id * n / p;
    }
}
