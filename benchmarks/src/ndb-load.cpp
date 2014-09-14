#include <NdbApi.hpp>
#include <stdio.h>
#include <iostream>
#include <thread>
#include <unistd.h>

#define DATABASE_NAME "benchmarks"
#define TABLE_NAME "transactions"

#define PRINT_ERROR(code,msg) \
	std::cerr << "Error in " << __FILE__ << ", line: " << __LINE__ \
			  << ", code: " << code \
			  << ", msg: " << msg << "." << std::endl
#define APIERROR(error) { PRINT_ERROR(error.code, error.message); exit(-1); }
#define BLOCK_LOW(id,p,n) ((id)*(n)/(p))


static bool createAccount(Ndb* ndb, const NdbDictionary::Table* table, int accountID, int numTxn) {
	NdbTransaction* batch = ndb->startTransaction();
	for (int txnID = 0; txnID < numTxn; txnID++) {
		NdbOperation* op = batch->getNdbOperation(table);
		if (op == NULL) {
			throw batch->getNdbError();
		}

		op->insertTuple();
		op->equal("account_id", accountID);
		op->equal("txn_id", txnID);
		op->setValue("timestamp", rand());
		op->setValue("posted", rand() % 2 == 0);
		op->setValue("amount", 200 * (float)rand() / RAND_MAX);
	}

	int result = batch->execute(NdbTransaction::Commit);
	batch->close();

	if (result == -1) {
		throw batch->getNdbError();
	} else {
		return true;
	}
}

static void insert(Ndb_cluster_connection* cluster_connection, int startAccountID, int endAccountID, int numTxnPerAccount) {
	Ndb ndb(cluster_connection, DATABASE_NAME);
	if (ndb.init()) {
		APIERROR(ndb.getNdbError());
	}

	const NdbDictionary::Dictionary* dict = ndb.getDictionary();
	const NdbDictionary::Table* table = dict->getTable(TABLE_NAME);
	if (table == NULL) {
		APIERROR(dict->getNdbError());
	}

	for (int accountID = startAccountID; accountID < endAccountID; accountID++) {
		for (int retries = 20; retries >= 0; retries--) {
			try {
				createAccount(&ndb, table, accountID, numTxnPerAccount);
				break;
			} catch (NdbError& error) {
				if (error.status == NdbError::TemporaryError && retries > 0) {
					std::cerr << "Retrying in 500ms for accountID = " <<  accountID << "!" << std::endl;
					usleep(500000);
					continue;
				}
				APIERROR(error);
				return;
			}
		}
	}
}

static void run(const char* connectionString, int startingAccountID, int numAccounts, int numTxnPerAccount, int numThreads) {
	Ndb_cluster_connection cluster_connection(connectionString);
	if (cluster_connection.connect(4, 5, 1)) {
		std::cerr << "Unable to connect to cluster management server" << std::endl;
		exit(1);
	}
	if (cluster_connection.wait_until_ready(30, 0) < 0) {
		std::cerr << "Unable to connect to datanodes" << std::endl;
		exit(1);
	}

	std::cout << "Connected to cluster; creating " << numThreads << " threads" << std::endl;
	std::thread* threads = new std::thread[numThreads];
	for (int thread = 0; thread < numThreads; thread++) {
		int startAccountID = BLOCK_LOW(thread, numThreads, numAccounts) + startingAccountID;
		int endAccountID = BLOCK_LOW(thread + 1, numThreads, numAccounts) + startingAccountID;
		threads[thread] = std::thread(insert, &cluster_connection, startAccountID, endAccountID, numTxnPerAccount);
	}
	for (int thread = 0; thread < numThreads; thread++) {
		threads[thread].join();
	}
	delete[] threads;
}


int main(int argc, char** argv) {
	if (argc != 6) {
		std::cerr << "usage: " << argv[0] << " connectionString startingAccountID numAccounts numTxnPerAccount numThreads" << std::endl;
		exit(1);
	}

	char* connectionString = argv[1];

	int startingAccountID;
	try {
		startingAccountID = std::stoi(argv[2]);
	} catch (std::invalid_argument e) {
		std::cerr << "Invalid startingAccountID: '" << argv[2] << "'" << std::endl;
		exit(1);
	} catch (std::out_of_range e) {
		std::cerr << "Invalid startingAccountID: '" << argv[2] << "'" << std::endl;
		exit(1);
	}
	if(startingAccountID < 1) {
		std::cerr << "Invalid startingAccountID: '" << argv[2] << "'; must be positive" << std::endl;
		exit(1);
	}

	int numAccounts;
	try {
		numAccounts = std::stoi(argv[3]);
	} catch (std::invalid_argument e) {
		std::cerr << "Invalid numAccounts: '" << argv[3] << "'" << std::endl;
		exit(1);
	} catch (std::out_of_range e) {
		std::cerr << "Invalid numAccounts: '" << argv[3] << "'" << std::endl;
		exit(1);
	}
	if(numAccounts < 1) {
		std::cerr << "Invalid numAccounts: '" << argv[3] << "'; must be positive" << std::endl;
		exit(1);
	}

	int numTxnPerAccount;
	try {
		numTxnPerAccount = std::stoi(argv[4]);
	} catch(std::invalid_argument e) {
		std::cerr << "Invalid numTxnPerAccount: '" << argv[4] << "'" << std::endl;
		exit(1);
	} catch (std::out_of_range e) {
		std::cerr << "Invalid numTxnPerAccount: '" << argv[4] << "'" << std::endl;
		exit(1);
	}
	if(numTxnPerAccount < 1) {
		std::cerr << "Invalid numTxnPerAccount: '" << argv[4] << "'; must be positive" << std::endl;
		exit(1);
	}

	int numThreads;
	try {
		numThreads = std::stoi(argv[5]);
	} catch(std::invalid_argument e) {
		std::cerr << "Invalid numThreads: '" << argv[5] << "'" << std::endl;
		exit(1);
	} catch (std::out_of_range e) {
		std::cerr << "Invalid numThreads: '" << argv[5] << "'" << std::endl;
		exit(1);
	}
	if(numThreads < 1) {
		std::cerr << "Invalid numThreads: '" << argv[5] << "'; must be positive" << std::endl;
		exit(1);
	}

	ndb_init();
	run(connectionString, startingAccountID, numAccounts, numTxnPerAccount, numThreads);
	ndb_end(0);
	return 0;
}
