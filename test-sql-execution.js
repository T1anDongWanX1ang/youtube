#!/usr/bin/env node

const mysql = require('mysql2/promise');
const fs = require('fs');
const path = require('path');

// 加载SQL语句
const sqlStatementsPath = path.join(__dirname, '../../../Users/Ash1na/DataWorkspace/config/sql-statements.json');
let sqlData;

try {
  sqlData = JSON.parse(fs.readFileSync(sqlStatementsPath, 'utf8'));
} catch (error) {
  console.error('无法加载SQL语句配置文件:', error.message);
  process.exit(1);
}

// 数据库配置
const dbConfig = {
  host: '127.0.0.1',
  port: 3306,
  user: 'root',
  password: 'root',
  database: 'tp_alarm',
  waitForConnections: true,
  connectionLimit: 5,
  queueLimit: 0
};

// 颜色输出
const colors = {
  reset: '\x1b[0m',
  green: '\x1b[32m',
  red: '\x1b[31m',
  yellow: '\x1b[33m',
  blue: '\x1b[36m',
  bold: '\x1b[1m'
};

async function testSqlExecution() {
  console.log(`\n${colors.bold}${colors.blue}=== SQL 执行测试 ===${colors.reset}\n`);
  console.log(`${colors.blue}数据库配置: ${dbConfig.user}@${dbConfig.host}:${dbConfig.port}/${dbConfig.database}${colors.reset}\n`);

  let connection;
  
  try {
    // 建立连接
    connection = await mysql.createConnection(dbConfig);
    console.log(`${colors.green}✓ 数据库连接成功${colors.reset}\n`);

    // 测试前5条SQL语句
    const testStatements = sqlData.statements.slice(0, 5);
    const results = [];

    console.log(`${colors.bold}测试前 5 条SQL语句:${colors.reset}\n`);

    for (let i = 0; i < testStatements.length; i++) {
      const stmt = testStatements[i];
      console.log(`${colors.bold}[${stmt.id}] ${stmt.name}${colors.reset}`);
      console.log(`描述: ${stmt.description}`);
      console.log(`分类: ${stmt.category}\n`);

      try {
        const startTime = Date.now();
        const [rows, fields] = await connection.execute(stmt.sql);
        const executionTime = Date.now() - startTime;

        const rowCount = Array.isArray(rows) ? rows.length : 0;
        console.log(`${colors.green}✓ 执行成功${colors.reset}`);
        console.log(`  - 返回行数: ${rowCount}`);
        console.log(`  - 执行时间: ${executionTime}ms`);
        
        if (rowCount > 0 && rows[0]) {
          console.log(`  - 字段列表: ${Object.keys(rows[0]).join(', ')}`);
          console.log(`  - 样本数据 (第1行):`);
          const sampleRow = rows[0];
          Object.keys(sampleRow).slice(0, 3).forEach(key => {
            console.log(`    • ${key}: ${sampleRow[key]}`);
          });
        }

        results.push({
          id: stmt.id,
          name: stmt.name,
          status: 'success',
          rowCount,
          executionTime,
          fields: fields ? fields.map(f => f.name) : []
        });

        console.log('');
      } catch (error) {
        console.log(`${colors.red}✗ 执行失败${colors.reset}`);
        console.log(`  错误: ${error.message}\n`);
        
        results.push({
          id: stmt.id,
          name: stmt.name,
          status: 'error',
          error: error.message
        });
      }
    }

    // 汇总报告
    console.log(`${colors.bold}${colors.blue}=== 执行汇总 ===${colors.reset}\n`);
    const successCount = results.filter(r => r.status === 'success').length;
    const errorCount = results.filter(r => r.status === 'error').length;

    console.log(`总计: ${results.length} 条语句`);
    console.log(`${colors.green}✓ 成功: ${successCount}${colors.reset}`);
    console.log(`${colors.red}✗ 失败: ${errorCount}${colors.reset}\n`);

    if (errorCount > 0) {
      console.log(`${colors.bold}失败的SQL:${colors.reset}`);
      results.filter(r => r.status === 'error').forEach(r => {
        console.log(`  [${r.id}] ${r.name}: ${r.error}`);
      });
      console.log('');
    }

    // 保存结果
    const reportFile = path.join(__dirname, 'sql-execution-report.json');
    fs.writeFileSync(reportFile, JSON.stringify({
      timestamp: new Date().toISOString(),
      database: `${dbConfig.user}@${dbConfig.host}:${dbConfig.port}/${dbConfig.database}`,
      totalStatements: sqlData.statements.length,
      testedStatements: results.length,
      successCount,
      errorCount,
      results
    }, null, 2));

    console.log(`${colors.green}✓ 报告已保存到: ${reportFile}${colors.reset}\n`);

  } catch (error) {
    console.error(`${colors.red}✗ 错误: ${error.message}${colors.reset}\n`);
    console.error(`${colors.yellow}提示: 请确保 MySQL 服务运行在 ${dbConfig.host}:${dbConfig.port}${colors.reset}`);
  } finally {
    if (connection) {
      await connection.end();
    }
  }
}

// 运行测试
testSqlExecution();
